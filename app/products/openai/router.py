"""OpenAI-compatible API router (/v1/*)."""

import base64
import binascii
import mimetypes
import asyncio
from dataclasses import dataclass
from typing import Annotated, Any, AsyncGenerator, AsyncIterable, Literal

import orjson
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from app.control.account.state_machine import is_manageable
from app.platform.auth.middleware import verify_api_key
from app.platform.errors import AppError, ValidationError, sanitize_exception
from app.platform.logging.logger import logger
from app.platform.storage import image_files_dir, video_files_dir
from app.control.model import registry as model_registry
from app.control.model.spec import ModelSpec
from app.control.account.quota_defaults import supports_mode
from .schemas import (
    ChatCompletionRequest,
    ImageGenerationRequest,
    VideoConfig,
    ImageConfig,
    ResponsesCreateRequest,
)
from .chat import completions as chat_completions

router = APIRouter(prefix="/v1")
_POOL_ID_TO_NAME = {0: "basic", 1: "super", 2: "heavy"}
_TAG_MODELS = "OpenAI - Models"
_TAG_CHAT = "OpenAI - Chat"
_TAG_RESPONSES = "OpenAI - Responses"
_TAG_IMAGES = "OpenAI - Images"
_TAG_VIDEOS = "OpenAI - Videos"
_TAG_FILES = "OpenAI - Files"


@dataclass(slots=True)
class _PendingVideoHold:
    key_record: Any
    model: str
    video_seconds: int
    video_resolution: str
    held_amount: float
    created_at: float


_PENDING_VIDEO_HOLDS: dict[str, _PendingVideoHold] = {}
_PENDING_VIDEO_HOLDS_LOCK = asyncio.Lock()


def _is_video_success(res: Any) -> bool:
    """Check if the video generation task result indicates successful completion."""
    if not isinstance(res, dict):
        return False
    if "error" in res or "err" in res:
        return False

    status = str(res.get("status") or "").lower()
    if status in ("completed", "success", "finished"):
        return True

    nested_data = res.get("data")
    if isinstance(nested_data, dict):
        if "error" in nested_data or "err" in nested_data:
            return False
        status = str(nested_data.get("status") or "").lower()
        if status in ("completed", "success", "finished"):
            return True

    url = (
        res.get("url")
        or res.get("video_url")
        or res.get("result_url")
        or (nested_data.get("url") if isinstance(nested_data, dict) else None)
        or (nested_data.get("video_url") if isinstance(nested_data, dict) else None)
        or (nested_data.get("result_url") if isinstance(nested_data, dict) else None)
    )
    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://") or url.startswith("/v1/files/")):
        return True

    return False


async def _process_pending_video_hold(task_id: str, result: dict[str, Any]) -> None:
    """Check if a pending video hold exists for task_id, and settle or refund billing accordingly."""
    import time as _time
    if not task_id:
        return

    keys_to_check = [str(task_id)]
    if ":" in str(task_id):
        keys_to_check.append(str(task_id).split(":", 1)[1])

    hold_entry: _PendingVideoHold | None = None
    matched_key: str | None = None

    async with _PENDING_VIDEO_HOLDS_LOCK:
        for k in keys_to_check:
            if k in _PENDING_VIDEO_HOLDS:
                hold_entry = _PENDING_VIDEO_HOLDS.pop(k)
                matched_key = k
                break
        if matched_key:
            for k in list(_PENDING_VIDEO_HOLDS.keys()):
                if k in keys_to_check:
                    _PENDING_VIDEO_HOLDS.pop(k, None)

    if hold_entry is None:
        return

    from app.control.billing.service import get_billing_service
    svc = get_billing_service()
    if svc is None:
        return

    if _is_video_success(result):
        duration_ms = int((_time.monotonic() - hold_entry.created_at) * 1000)
        try:
            await svc.record_usage(
                hold_entry.key_record,
                model=hold_entry.model,
                endpoint="video",
                video_seconds=hold_entry.video_seconds,
                video_resolution=hold_entry.video_resolution,
                request_id=str(task_id),
                duration_ms=duration_ms,
                held_amount=hold_entry.held_amount,
            )
            logger.info("Video task {} completed successfully, settled billing: ${}", task_id, hold_entry.held_amount)
        except Exception as exc:
            logger.warning("Failed to settle billing for completed video task {}: {}", task_id, exc)

    elif _is_video_failed(result):
        try:
            await svc.refund_hold(hold_entry.key_record.key, hold_entry.held_amount)
            logger.info("Video task {} failed, refunded pre-hold: ${}", task_id, hold_entry.held_amount)
        except Exception as exc:
            logger.warning("Failed to refund pre-hold for video task {}: {}", task_id, exc)
    else:
        # Task still in progress, restore hold entry for future polls
        async with _PENDING_VIDEO_HOLDS_LOCK:
            _PENDING_VIDEO_HOLDS[matched_key] = hold_entry


async def _cleanup_stale_video_holds(ttl_seconds: float = 1800.0) -> None:
    """Refund and remove pending video holds that have been unpolled longer than ttl_seconds."""
    import time as _time
    now = _time.monotonic()
    expired: list[tuple[str, _PendingVideoHold]] = []

    async with _PENDING_VIDEO_HOLDS_LOCK:
        for task_id, hold in list(_PENDING_VIDEO_HOLDS.items()):
            if now - hold.created_at > ttl_seconds:
                expired.append((task_id, hold))
                _PENDING_VIDEO_HOLDS.pop(task_id, None)

    if not expired:
        return

    from app.control.billing.service import get_billing_service
    svc = get_billing_service()

    for task_id, hold in expired:
        logger.info("Video task {} expired after {}s without poll, refunding ${}", task_id, ttl_seconds, hold.held_amount)
        if svc is not None:
            try:
                await svc.refund_hold(hold.key_record.key, hold.held_amount)
            except Exception as exc:
                logger.warning("Failed to refund expired video hold {}: {}", task_id, exc)



async def _available_pools(request: Request) -> frozenset[str]:
    repo = getattr(request.app.state, "repository", None)
    if repo is None:
        return frozenset()

    snapshot = await repo.runtime_snapshot()
    pools = {record.pool for record in snapshot.items if is_manageable(record)}
    return frozenset(pools)


def _model_available_for_pools(spec: ModelSpec, pools: frozenset[str]) -> bool:
    if not spec.enabled:
        return False
    for pool_id in spec.pool_candidates():
        pool = _POOL_ID_TO_NAME[pool_id]
        if pool in pools and supports_mode(pool, int(spec.mode_id)):
            return True
    return False


# ---------------------------------------------------------------------------
# /v1/models
# ---------------------------------------------------------------------------


@router.get("/models", tags=[_TAG_MODELS], dependencies=[Depends(verify_api_key)])
async def list_models(request: Request):
    import time
    from app.platform.config.snapshot import get_config as _cfg

    cfg = _cfg()
    exclude_list = cfg.get_list("providers.newapi.exclude_models", [])
    exclude = {str(item).strip() for item in exclude_list if item}

    pools = await _available_pools(request)
    models = [
        {
            "id": m.model_name,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "xai",
            "name": m.public_name,
        }
        for m in model_registry.list_enabled()
        if _model_available_for_pools(m, pools) and m.model_name not in exclude
    ]

    # Merge NewAPI upstream models if enabled and configured
    from app.control.provider.newapi import is_newapi_enabled, list_models as newapi_list

    if is_newapi_enabled() and cfg.get_bool("providers.newapi.merge_models", True):
        local_ids = {m["id"] for m in models}
        try:
            # Extract all models configured with custom pricing
            pricing_models = set(cfg.raw().get("billing", {}).get("pricing", {}).keys())
            
            # Extract all models configured in enabled channels
            channel_models = set()
            for chan in cfg.get_list("providers.newapi.channels", []):
                if isinstance(chan, dict) and chan.get("enabled", True):
                    for mname in chan.get("models", []):
                        channel_models.add(str(mname).strip())

            upstream = await newapi_list()
            for um in upstream:
                mid = um.get("id")
                if mid not in local_ids and mid not in exclude:
                    # Only show if the model is explicitly priced OR configured in a channel
                    if mid in pricing_models or mid in channel_models:
                        models.append(um)
        except Exception as exc:
            logger.debug("newapi model merge skipped: error={}", exc)

    # Attach pricing info to each model in the list
    from app.control.billing.pricing import get_pricing, video_cost

    for m in models:
        mid = m.get("id", "")
        pricing = get_pricing(mid)
        if pricing.per_request > 0:
            m["price"] = f"¥{pricing.per_request:.2f} / 次"
            m["per_request_price"] = pricing.per_request
        elif pricing.is_video:
            rate_720p = video_cost(1, resolution="720p", model=mid)
            if rate_720p > 0:
                m["price"] = f"¥{rate_720p:.2f} / 秒"
                m["per_second_price"] = rate_720p
            else:
                m["price"] = "按秒计费"
        elif pricing.input > 0 or pricing.output > 0:
            m["price"] = f"¥{pricing.input:.2f}/1M (in) | ¥{pricing.output:.2f}/1M (out)"

    return JSONResponse({"object": "list", "data": models})


@router.get(
    "/models/{model_id}", tags=[_TAG_MODELS], dependencies=[Depends(verify_api_key)]
)
async def get_model_endpoint(model_id: str, request: Request):
    import time
    from app.control.billing.pricing import get_pricing, video_cost

    spec = model_registry.get(model_id)
    pools = await _available_pools(request)
    if spec is None or not _model_available_for_pools(spec, pools):
        # Fall back to NewAPI upstream check if enabled
        from app.control.provider.newapi import is_newapi_enabled, list_models as newapi_list
        from app.platform.config.snapshot import get_config as _cfg

        if is_newapi_enabled() and _cfg().get_bool("providers.newapi.merge_models", True):
            try:
                upstream = await newapi_list()
                matched = next((um for um in upstream if um.get("id") == model_id), None)
                if matched:
                    pricing = get_pricing(model_id)
                    res = dict(matched)
                    if pricing.per_request > 0:
                        res["price"] = f"¥{pricing.per_request:.2f} / 次"
                        res["per_request_price"] = pricing.per_request
                    return JSONResponse(res)
            except Exception:
                pass

        return JSONResponse(
            {
                "error": {
                    "message": f"Model {model_id!r} not found",
                    "type": "invalid_request_error",
                }
            },
            status_code=404,
        )

    res = {
        "id": spec.model_name,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "xai",
        "name": spec.public_name,
    }
    pricing = get_pricing(spec.model_name)
    if pricing.per_request > 0:
        res["price"] = f"¥{pricing.per_request:.2f} / 次"
        res["per_request_price"] = pricing.per_request
    return JSONResponse(res)


# ---------------------------------------------------------------------------
# SSE streaming helpers
# ---------------------------------------------------------------------------


async def _safe_sse(stream: AsyncIterable[str]) -> AsyncGenerator[str, None]:
    """Wrap an SSE stream, converting exceptions to in-band error events."""
    try:
        async for chunk in stream:
            yield chunk
    except AppError as exc:
        payload = orjson.dumps({"error": exc.to_dict()["error"]}).decode()
        yield f"event: error\ndata: {payload}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        payload = orjson.dumps(
            {"error": {"message": sanitize_exception(exc), "type": "server_error"}}
        ).decode()
        yield f"event: error\ndata: {payload}\n\n"
        yield "data: [DONE]\n\n"


_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive"}


# ---------------------------------------------------------------------------
# /v1/chat/completions
# ---------------------------------------------------------------------------

_VALID_ROLES = {"developer", "system", "user", "assistant", "tool"}
_USER_BLOCK_TYPES = {"text", "image_url", "input_audio", "file"}
_ALLOWED_SIZES = {"1280x720", "720x1280", "1792x1024", "1024x1792", "1024x1024"}
_EFFORT_VALUES = {"none", "minimal", "low", "medium", "high", "xhigh"}
_LITE_IMAGE_MODELS = {"grok-imagine-image-lite"}


def _validate_chat(req: ChatCompletionRequest) -> None:
    from app.platform.errors import ValidationError

    spec = model_registry.get(req.model)
    if spec is None or not spec.enabled:
        raise ValidationError(
            f"Model {req.model!r} does not exist or you do not have access to it.",
            param="model",
            code="model_not_found",
        )
    if not req.messages:
        raise ValidationError("messages cannot be empty", param="messages")
    for i, msg in enumerate(req.messages):
        if msg.role not in _VALID_ROLES:
            raise ValidationError(
                f"role must be one of {sorted(_VALID_ROLES)}",
                param=f"messages.{i}.role",
            )
    if req.temperature is not None and not (0 <= req.temperature <= 2):
        raise ValidationError(
            "temperature must be between 0 and 2", param="temperature"
        )
    if req.top_p is not None and not (0 <= req.top_p <= 1):
        raise ValidationError("top_p must be between 0 and 1", param="top_p")
    if req.reasoning_effort is not None and req.reasoning_effort not in _EFFORT_VALUES:
        raise ValidationError(
            f"reasoning_effort must be one of {sorted(_EFFORT_VALUES)}",
            param="reasoning_effort",
        )


def _validate_image_n(model_name: str, n: int, *, param: str) -> None:
    max_n = 4 if model_name in _LITE_IMAGE_MODELS else 10
    if not (1 <= n <= max_n):
        raise ValidationError(
            f"n must be between 1 and {max_n} for model {model_name!r}",
            param=param,
        )


def _validate_image_edit_n(n: int, *, param: str) -> None:
    if not (1 <= n <= 2):
        raise ValidationError("n must be between 1 and 2 for image edit", param=param)


async def _upload_to_data_uri(upload: UploadFile, *, param: str) -> str:
    raw = await upload.read()
    if not raw:
        raise ValidationError("Uploaded image cannot be empty", param=param)

    mime = (
        (upload.content_type or "").strip().lower()
        or mimetypes.guess_type(upload.filename or "")[0]
        or "application/octet-stream"
    )
    if not mime.startswith("image/"):
        raise ValidationError("Uploaded file must be an image", param=param)

    try:
        blob_b64 = base64.b64encode(raw).decode("ascii")
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValidationError("Failed to encode uploaded image", param=param) from exc
    return f"data:{mime};base64,{blob_b64}"


async def _extract_images_from_payload(payload: Any) -> list[str]:
    """Helper to extract flat list of image URLs/Base64 from various possible fields."""
    urls = []
    if not payload:
        return urls

    async def process_item(item: Any):
        if isinstance(item, str):
            if item.strip():
                urls.append(item.strip())
        elif isinstance(item, dict):
            for key in ("image_url", "url", "image"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    urls.append(val.strip())
                    break
        elif hasattr(item, "read") and hasattr(item, "filename"):  # UploadFile-like
            try:
                data_uri = await _upload_to_data_uri(item, param="input_reference")
                if data_uri:
                    urls.append(data_uri)
            except Exception:
                pass

    if isinstance(payload, dict):
        for field in ("images", "input_reference", "input_references", "reference_images", "image_refs"):
            val = payload.get(field)
            if not val:
                continue
            if isinstance(val, list):
                for sub_item in val:
                    await process_item(sub_item)
            else:
                await process_item(val)
    elif isinstance(payload, list):
        for item in payload:
            await process_item(item)
    else:
        await process_item(payload)

    return urls


def _ensure_gateway_public_url(val: str) -> str:
    if not isinstance(val, str) or not val.strip():
        return val
    v = val.strip()
    if not v.startswith("data:"):
        return v

    import base64
    import uuid
    from app.platform.storage import save_local_image
    from app.platform.config.snapshot import get_config as _cfg

    try:
        header, data = v.split(",", 1)
        mime = header.split(";", 1)[0].replace("data:", "")
        raw_data = base64.b64decode(data)
        file_id = str(uuid.uuid4())
        save_local_image(raw_data, mime, file_id)
        
        app_url = _cfg().get_str("app.app_url", "").rstrip("/")
        if not app_url:
            app_url = "http://localhost:8000" # fallback
        return f"{app_url}/v1/files/image?id={file_id}"
    except Exception as e:
        logger.error("Failed to convert base64 data to local gateway URL: {}", e)
        return v


def _standardize_newapi_video_body(body: dict[str, Any], urls: list[str]) -> None:
    model = body.get("model", "")

    # Standardize size / aspect_ratio
    raw_size = str(body.get("size", "")).strip()
    if raw_size == "720x1280":
        if "aspect_ratio" not in body:
            body["aspect_ratio"] = "9:16"
        body.pop("size", None)
    elif raw_size == "1280x720":
        if "aspect_ratio" not in body:
            body["aspect_ratio"] = "16:9"
        body.pop("size", None)

    # Standardize duration
    sec = body.get("seconds") or body.get("duration")
    if sec is not None:
        try:
            sec_int = int(sec)
            body["duration"] = sec_int
            body["seconds"] = str(sec_int)
        except (ValueError, TypeError):
            pass

    if "sora" in model.lower() or "tejiasd" in model.lower():
        if "resolution" not in body:
            body["resolution"] = "720p"
        if urls:
            if not body.get("image_url"):
                body["image_url"] = urls[0]
            if len(urls) > 1 and not body.get("reference_image_urls") and not body.get("reference_images"):
                body["reference_image_urls"] = urls[1:]

    elif model == "grok-imagine-video-1.5-preview":
        if urls:
            body["images"] = [urls[0]]
        else:
            body["images"] = []
        body.pop("input_reference", None)
        body.pop("input_references", None)
        body.pop("reference_images", None)
    elif model == "sd2-c7":
        if "image_refs" not in body or not body["image_refs"]:
            if urls:
                body["image_refs"] = urls[:9]
        elif isinstance(body["image_refs"], list):
            body["image_refs"] = [str(u) for u in body["image_refs"] if u][:9]
        if urls and "input_reference" not in body:
            body["input_reference"] = urls[0]
        if urls and "images" not in body:
            body["images"] = urls[:9]
    elif model.startswith("sd2-") or model.startswith("sd2.") or model.startswith("seedance") or model == "sd2.5" or model == "sd-c6" or model.startswith("ld-") or model.startswith("sdas-"):
        max_imgs = 50 if "2.5" in model else 9
        max_vids = 10 if "2.5" in model else 3
        max_auds = 10 if "2.5" in model else 3
        if "image_refs" not in body or not body["image_refs"]:
            if urls:
                body["image_refs"] = urls[:max_imgs]
        elif isinstance(body["image_refs"], list):
            body["image_refs"] = [str(u) for u in body["image_refs"] if u][:max_imgs]
        if "video_refs" in body and isinstance(body["video_refs"], list):
            body["video_refs"] = [str(v) for v in body["video_refs"] if v][:max_vids]
        if "audio_refs" in body and isinstance(body["audio_refs"], list):
            body["audio_refs"] = [str(a) for a in body["audio_refs"] if a][:max_auds]
        if urls and "input_reference" not in body:
            body["input_reference"] = urls[0]
        if urls and "images" not in body:
            body["images"] = urls[:max_imgs]
        if "2.5" in model or model == "sd-c6":
            body["duration"] = 10
        elif "h3" in model:
            body["duration"] = 15

    elif model.startswith("sd2.0-") or model.startswith("video-"):
        # Map to newtoken.club format
        img_list = []
        if "image_refs" in body and isinstance(body["image_refs"], list):
            img_list = body.pop("image_refs")
        elif "extra_images" in body and isinstance(body["extra_images"], list):
            img_list = body.pop("extra_images")
        elif "images" in body and isinstance(body["images"], list):
            img_list = body.pop("images")
        else:
            img_list = [u for u in urls if ".mp3" not in u.lower() and ".wav" not in u.lower() and ".mp4" not in u.lower()]

        # Convert Base64 data URIs to gateway public URLs
        img_list = [_ensure_gateway_public_url(u) for u in img_list]

        if img_list:
            body["image_url"] = img_list[0]
            if len(img_list) > 1:
                body["extra_images"] = img_list[1:]

        if "video_refs" in body and isinstance(body["video_refs"], list):
            body["extra_videos"] = [_ensure_gateway_public_url(v) for v in body.pop("video_refs")]
        elif "extra_videos" in body and isinstance(body["extra_videos"], list):
            body["extra_videos"] = [_ensure_gateway_public_url(v) for v in body["extra_videos"]]
        else:
            video_list = [u for u in urls if ".mp4" in u.lower()]
            if video_list:
                body["extra_videos"] = [_ensure_gateway_public_url(v) for v in video_list]

        if "audio_refs" in body and isinstance(body["audio_refs"], list):
            body["extra_audios"] = [_ensure_gateway_public_url(a) for a in body.pop("audio_refs")]
        elif "extra_audios" in body and isinstance(body["extra_audios"], list):
            body["extra_audios"] = [_ensure_gateway_public_url(a) for a in body["extra_audios"]]
        else:
            audio_list = [u for u in urls if ".mp3" in u.lower() or ".wav" in u.lower()]
            if audio_list:
                body["extra_audios"] = [_ensure_gateway_public_url(a) for a in audio_list]
    else:
        body["images"] = urls
        if urls:
            body["input_reference"] = urls[0]
            body["input_references"] = [{"image_url": u} for u in urls]
            body["reference_images"] = urls


@router.post(
    "/chat/completions", tags=[_TAG_CHAT], dependencies=[Depends(verify_api_key)]
)
async def chat_completions_endpoint(request: Request, req: ChatCompletionRequest):
    import asyncio, time as _time

    from app.platform.config.snapshot import get_config

    billing_key = getattr(request.state, "billing_key", None)
    _start = _time.monotonic()

    cfg = get_config()
    is_stream = (
        req.stream if req.stream is not None else cfg.get_bool("features.stream", True)
    )

    spec = model_registry.get(req.model)

    # ── NewAPI Fallback: model not in Grok registry ──────────────────
    if spec is None:
        from app.control.provider.newapi import is_newapi_enabled, chat_completions as newapi_chat

        if not is_newapi_enabled():
            raise ValidationError(
                f"Model {req.model!r} does not exist or you do not have access to it.",
                param="model",
                code="model_not_found",
            )

        messages = [m.model_dump(exclude_none=True) for m in req.messages]
        try:
            result = await newapi_chat(
                model=req.model,
                messages=messages,
                stream=is_stream,
                temperature=req.temperature or 0.8,
                top_p=req.top_p or 0.95,
                tools=req.tools,
                tool_choice=req.tool_choice,
            )
        except Exception as exc:
            logger.exception(
                "newapi chat proxy failed: model={} error={}", req.model, exc,
            )
            if is_stream:
                _err_msg = str(exc)

                async def _err_stream():
                    payload = orjson.dumps(
                        {"error": {"message": _err_msg, "type": "server_error"}}
                    ).decode()
                    yield f"event: error\ndata: {payload}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    _err_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
                )
            raise

        # Billing for NewAPI non-streaming
        if isinstance(result, dict):
            if billing_key is not None:
                from app.control.billing.service import get_billing_service
                svc = get_billing_service()
                if svc is not None:
                    usage = result.get("usage", {})
                    duration_ms = int((_time.monotonic() - _start) * 1000)
                    asyncio.create_task(
                        svc.record_usage(
                            billing_key,
                            model=req.model,
                            endpoint="chat",
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            request_id=result.get("id", ""),
                            duration_ms=duration_ms,
                        )
                    )
            return JSONResponse(result)

        # Streaming: result is StreamWithUsage — wrap it to bill after stream ends
        from app.control.provider.newapi import StreamWithUsage

        _bk = billing_key
        _model = req.model

        async def _newapi_stream_with_billing():
            async for line in result:
                yield line
            # Stream ended — now record billing from collected usage
            if _bk is not None and isinstance(result, StreamWithUsage) and result.usage:
                from app.control.billing.service import get_billing_service
                svc = get_billing_service()
                if svc is not None:
                    u = result.usage
                    duration_ms = int((_time.monotonic() - _start) * 1000)
                    asyncio.create_task(
                        svc.record_usage(
                            _bk,
                            model=_model,
                            endpoint="chat",
                            prompt_tokens=u.get("prompt_tokens", 0),
                            completion_tokens=u.get("completion_tokens", 0),
                            request_id="",
                            duration_ms=duration_ms,
                        )
                    )

        return StreamingResponse(
            _newapi_stream_with_billing(), media_type="text/event-stream", headers=_SSE_HEADERS
        )

    # ── Grok native path (unchanged) ─────────────────────────────────
    _validate_chat(req)
    messages = [m.model_dump(exclude_none=True) for m in req.messages]

    # Determine endpoint type for billing
    if spec.is_image_edit():
        _billing_endpoint = "image_edit"
    elif spec.is_image():
        _billing_endpoint = "image"
    elif spec.is_video():
        _billing_endpoint = "video"
    else:
        _billing_endpoint = "chat"

    try:
        # Dispatch by model capability.
        if spec.is_image_edit():
            from .images import edit as img_edit

            cfg = req.image_config or ImageConfig()
            _validate_image_edit_n(cfg.n or 1, param="image_config.n")
            result = await img_edit(
                model=req.model,
                messages=messages,
                n=cfg.n or 1,
                size=cfg.size or "1024x1024",
                response_format=cfg.response_format or "url",
                stream=is_stream,
                chat_format=True,
            )

        elif spec.is_image():
            from .images import generate as img_gen

            cfg = req.image_config or ImageConfig()
            size = cfg.size or "1024x1024"
            fmt = cfg.response_format or "url"
            n = cfg.n or 1
            _validate_image_n(req.model, n, param="image_config.n")
            # Extract prompt from last user message.
            prompt = next(
                (
                    m.content
                    for m in reversed(req.messages)
                    if m.role == "user"
                    and isinstance(m.content, str)
                    and m.content.strip()
                ),
                "",
            )
            result = await img_gen(
                model=req.model,
                prompt=prompt or "",
                n=n,
                size=size,
                response_format=fmt,
                stream=is_stream,
                chat_format=True,
            )

        elif spec.is_video():
            from .video import completions as vid_comp

            vcfg = req.video_config or VideoConfig()
            from .video import validate_video_length as _validate_video_length

            _validate_video_length(vcfg.seconds or 6)
            result = await vid_comp(
                model=req.model,
                messages=messages,
                stream=is_stream,
                seconds=vcfg.seconds or 6,
                size=vcfg.size or "720x1280",
                resolution_name=vcfg.resolution_name,
                preset=vcfg.preset,
            )

        else:
            # reasoning_effort=None → config default; "none" → off; otherwise → on.
            if req.reasoning_effort is None:
                emit_think: bool | None = None
            else:
                emit_think = req.reasoning_effort != "none"
            result = await chat_completions(
                model=req.model,
                messages=messages,
                stream=is_stream,
                emit_think=emit_think,
                tools=req.tools,
                tool_choice=req.tool_choice,
                temperature=req.temperature or 0.8,
                top_p=req.top_p or 0.95,
            )

    except AppError:
        raise
    except Exception as exc:
        logger.exception(
            "chat completions endpoint failed: model={} stream={} error={}",
            req.model,
            is_stream,
            exc,
        )
        if is_stream:
            _err_msg = str(
                exc
            )  # capture before Python clears the except-scope variable

            async def _err_stream():
                payload = orjson.dumps(
                    {"error": {"message": _err_msg, "type": "server_error"}}
                ).decode()
                yield f"event: error\ndata: {payload}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                _err_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
            )
        raise

    # Billing: record usage for non-streaming dict responses
    if isinstance(result, dict):
        if billing_key is not None:
            from app.control.billing.service import get_billing_service
            svc = get_billing_service()
            if svc is not None:
                usage = result.get("usage", {})
                duration_ms = int((_time.monotonic() - _start) * 1000)
                asyncio.create_task(
                    svc.record_usage(
                        billing_key,
                        model=req.model,
                        endpoint=_billing_endpoint,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        request_id=result.get("id", ""),
                        duration_ms=duration_ms,
                    )
                )
        return JSONResponse(result)
    return StreamingResponse(
        _safe_sse(result), media_type="text/event-stream", headers=_SSE_HEADERS
    )


# ---------------------------------------------------------------------------
# /v1/responses  (OpenAI Responses API)
# ---------------------------------------------------------------------------


async def _safe_sse_responses(stream) -> AsyncGenerator[str, None]:
    """SSE wrapper that converts errors to Responses API error events."""
    try:
        async for chunk in stream:
            yield chunk
    except Exception as exc:
        from app.platform.errors import AppError

        if isinstance(exc, AppError):
            err = exc.to_dict()["error"]
        else:
            err = {
                "message": sanitize_exception(exc),
                "type": "server_error",
                "code": None,
                "param": None,
            }
        payload = orjson.dumps({"type": "error", **err}).decode()
        yield f"event: error\ndata: {payload}\n\n"
        yield "data: [DONE]\n\n"


@router.post(
    "/responses", tags=[_TAG_RESPONSES], dependencies=[Depends(verify_api_key)]
)
async def responses_endpoint(req: ResponsesCreateRequest):
    from app.platform.config.snapshot import get_config
    from app.platform.errors import ValidationError as _ValidationError

    spec = model_registry.get(req.model)
    if spec is None or not spec.enabled:
        raise _ValidationError(
            f"Model {req.model!r} does not exist or you do not have access to it.",
            param="model",
            code="model_not_found",
        )
    if not req.input:
        raise _ValidationError("input cannot be empty", param="input")

    cfg = get_config()
    is_stream = (
        req.stream if req.stream is not None else cfg.get_bool("features.stream", True)
    )

    # Map reasoning param → emit_think flag.
    # reasoning=None → use config; reasoning.effort="none" → off; otherwise on.
    if req.reasoning is None:
        emit_think = cfg.get_bool("features.thinking", True)
    elif isinstance(req.reasoning, dict) and req.reasoning.get("effort") == "none":
        emit_think = False
    else:
        emit_think = True

    from .responses import create as responses_create

    result = await responses_create(
        model=req.model,
        input_val=req.input,
        instructions=req.instructions,
        stream=is_stream,
        emit_think=emit_think,
        temperature=req.temperature or 0.8,
        top_p=req.top_p or 0.95,
        tools=req.tools or None,
        tool_choice=req.tool_choice,
    )

    if isinstance(result, dict):
        return JSONResponse(result)
    return StreamingResponse(
        _safe_sse_responses(result),
        media_type = "text/event-stream",
        headers    = _SSE_HEADERS,
    )


# ---------------------------------------------------------------------------
# /v1/images/generations (standalone image endpoint)
# ---------------------------------------------------------------------------


@router.post(
    "/images/generations", tags=[_TAG_IMAGES], dependencies=[Depends(verify_api_key)]
)
async def image_generations(request: Request, req: ImageGenerationRequest):
    import asyncio, time as _time

    billing_key = getattr(request.state, "billing_key", None)
    _start = _time.monotonic()

    spec = model_registry.get(req.model)

    # ── NewAPI Fallback for image models ──────────────────────────────
    if spec is None or not spec.enabled or not spec.is_image():
        from app.control.provider.newapi import is_newapi_enabled, image_generations as newapi_img

        if not is_newapi_enabled():
            raise ValidationError(
                f"Model {req.model!r} is not an image model", param="model"
            )

        result = await newapi_img(
            model=req.model,
            prompt=req.prompt,
            n=req.n or 1,
            size=req.size or "1024x1024",
            response_format=req.response_format or "url",
            quality=req.quality,
            output_format=req.output_format,
            background=req.background,
            output_compression=req.output_compression,
        )

        if billing_key is not None:
            from app.control.billing.service import get_billing_service
            from app.control.billing.pricing import get_pricing
            svc = get_billing_service()
            if svc is not None:
                pricing = get_pricing(req.model)
                duration_ms = int((_time.monotonic() - _start) * 1000)
                asyncio.create_task(
                    svc.record_usage(
                        billing_key,
                        model=req.model,
                        endpoint="image",
                        request_id=str(result.get("created", "")),
                        duration_ms=duration_ms,
                    )
                )

        return JSONResponse(result)

    # ── Grok native image path (unchanged) ───────────────────────────
    _validate_image_n(req.model, req.n or 1, param="n")

    from .images import generate as img_gen

    result = await img_gen(
        model=req.model,
        prompt=req.prompt,
        n=req.n or 1,
        size=req.size or "1024x1024",
        response_format=req.response_format or "url",
        stream=False,
        chat_format=False,
    )

    if billing_key is not None:
        from app.control.billing.service import get_billing_service
        svc = get_billing_service()
        if svc is not None:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            asyncio.create_task(
                svc.record_usage(
                    billing_key,
                    model=req.model,
                    endpoint="image",
                    request_id=result.get("created", ""),
                    duration_ms=duration_ms,
                )
            )

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# /v1/videos (OpenAI videos.create surface)
# ---------------------------------------------------------------------------


@router.post("/videos", tags=[_TAG_VIDEOS], dependencies=[Depends(verify_api_key)])
async def videos_create(request: Request):
    import asyncio, time as _time

    billing_key = getattr(request.state, "billing_key", None)
    content_type = request.headers.get("content-type", "")

    json_raw_body: dict[str, Any] | None = None

    if "application/json" in content_type:
        json_raw_body = await request.json()
        model = json_raw_body.get("model")
        prompt = json_raw_body.get("prompt")
        seconds = json_raw_body.get("seconds") or json_raw_body.get("duration") or json_raw_body.get("video_length") or 6
        size = json_raw_body.get("size") or json_raw_body.get("aspect_ratio") or "720x1280"
        resolution_name = json_raw_body.get("resolution_name") or json_raw_body.get("resolution")
        preset = json_raw_body.get("preset")
        aspect_ratio = json_raw_body.get("aspect_ratio")
        resolution = json_raw_body.get("resolution")
        urls = await _extract_images_from_payload(json_raw_body)
    else:
        form = await request.form()
        payload = {}
        for k in form.keys():
            norm_k = k.rstrip("[]")
            val_list = form.getlist(k)
            if norm_k in payload:
                if isinstance(payload[norm_k], list):
                    payload[norm_k].extend(val_list)
                else:
                    payload[norm_k] = [payload[norm_k]] + val_list
            else:
                if len(val_list) == 1:
                    payload[norm_k] = val_list[0]
                else:
                    payload[norm_k] = val_list

        model = payload.get("model")
        prompt = payload.get("prompt")
        seconds = payload.get("seconds") or payload.get("duration") or 6
        size = payload.get("size") or "720x1280"
        resolution_name = payload.get("resolution_name")
        preset = payload.get("preset")
        aspect_ratio = payload.get("aspect_ratio")
        resolution = payload.get("resolution")
        urls = await _extract_images_from_payload(payload)

    if not model or not prompt:
        raise ValidationError("model and prompt are required fields", param="model")

    # ── NewAPI Fallback: third-party video models ────────────────────
    from app.control.provider.newapi import (
        is_newapi_enabled, is_third_party_video_model, video_create as newapi_video_create,
    )

    if is_third_party_video_model(model) and is_newapi_enabled():
        # Build JSON body for /v1/video/create or /v1/videos
        if json_raw_body is not None:
            body: dict[str, Any] = dict(json_raw_body)
        else:
            body: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
            }
        try:
            sec_int = int(seconds)
            body["seconds"] = str(sec_int)
            body["duration"] = sec_int
        except (ValueError, TypeError):
            body["seconds"] = str(seconds)
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        elif size and ":" in str(size):
            body["aspect_ratio"] = str(size)
        elif size:
            body["size"] = str(size)
        if resolution_name:
            body["size"] = resolution_name.upper()
        elif resolution:
            body["size"] = resolution.upper()

        # Standardize references for NewAPI
        _standardize_newapi_video_body(body, urls)

        # Pre-hold billing check for third-party models
        held_amount = 0.0
        if billing_key is not None:
            from app.control.billing.service import get_billing_service
            from app.control.billing.pricing import get_pricing, video_cost

            svc = get_billing_service()
            if svc is not None:
                pricing = get_pricing(model)
                if pricing.per_request > 0:
                    held_amount = pricing.per_request
                elif pricing.is_video:
                    raw_res = str(resolution_name or resolution or "720p").strip().lower()
                    if "480" in raw_res:
                        res = "480p"
                    else:
                        res = "720p"
                    try:
                        video_sec = int(seconds)
                    except (ValueError, TypeError):
                        video_sec = 6
                    held_amount = video_cost(video_sec, resolution=res, model=model)
                else:
                    held_amount = 0.04

                if held_amount > 0:
                    ok = await svc.hold_balance(billing_key.key, held_amount)
                    if not ok:
                        return JSONResponse(
                            {
                                "error": {
                                    "message": "Insufficient balance",
                                    "type": "billing_error",
                                    "code": "insufficient_balance",
                                }
                            },
                            status_code=402,
                        )

        _start = _time.monotonic()
        try:
            result = await newapi_video_create(body=body)
        except Exception as exc:
            if held_amount > 0 and billing_key is not None:
                from app.control.billing.service import get_billing_service
                svc = get_billing_service()
                if svc is not None:
                    await svc.refund_hold(billing_key.key, held_amount)
            logger.exception(
                "newapi video_create proxy failed: model={} error={}", model, exc,
            )
            return JSONResponse(
                {"error": {"message": sanitize_exception(exc), "type": "server_error"}},
                status_code=502,
            )

        # Register pending video hold for settlement upon poll completion
        task_id = result.get("id") or result.get("task_id") or ""
        if not task_id and isinstance(result.get("data"), dict):
            task_id = result.get("data").get("id") or result.get("data").get("task_id") or ""

        if billing_key is not None and held_amount > 0 and task_id:
            try:
                video_sec = int(seconds)
            except (ValueError, TypeError):
                video_sec = 6
            res_str = str(resolution_name or resolution or "720p")
            hold_entry = _PendingVideoHold(
                key_record=billing_key,
                model=model,
                video_seconds=video_sec,
                video_resolution=res_str,
                held_amount=held_amount,
                created_at=_time.monotonic(),
            )
            async with _PENDING_VIDEO_HOLDS_LOCK:
                _PENDING_VIDEO_HOLDS[str(task_id)] = hold_entry
                if ":" in str(task_id):
                    _PENDING_VIDEO_HOLDS[str(task_id).split(":", 1)[1]] = hold_entry
            asyncio.create_task(_cleanup_stale_video_holds())

        return JSONResponse(result)

    # ── Grok native path ─────────────────────────────────────────────
    from .video import create_video

    references_payload = None
    if urls:
        references_payload = [{"image_url": u} for u in urls[:7]]

    # ── Pre-hold: freeze estimated cost before submission ────────────
    held_amount = 0.0
    if billing_key is not None:
        from app.control.billing.service import get_billing_service
        from app.control.billing.pricing import video_cost

        svc = get_billing_service()
        if svc is not None:
            held_amount = video_cost(int(seconds), resolution=resolution_name or "720p")
            if held_amount > 0:
                ok = await svc.hold_balance(billing_key.key, held_amount)
                if not ok:
                    return JSONResponse(
                        {"error": {"message": "Insufficient balance", "type": "billing_error", "code": "insufficient_balance"}},
                        status_code=402,
                    )

    result = await create_video(
        model=model or "grok-video",
        prompt=prompt,
        seconds=int(seconds),
        size=size or "720x1280",
        resolution_name=resolution_name,
        preset=preset,
        input_references=references_payload,
        billing_key=billing_key,
        held_amount=held_amount,
    )

    return JSONResponse(result)



@router.get(
    "/videos/{video_id}", tags=[_TAG_VIDEOS], dependencies=[Depends(verify_api_key)]
)
async def videos_retrieve(video_id: str, request: Request):
    from .video import retrieve

    try:
        return JSONResponse(await retrieve(video_id))
    except Exception:
        pass

    # ── NewAPI Fallback: try querying third-party video status ────────
    from app.control.provider.newapi import is_newapi_enabled, video_query as newapi_video_query

    if is_newapi_enabled():
        try:
            result = await newapi_video_query(video_id)
            await _process_pending_video_hold(video_id, result)
            billing_key = getattr(request.state, "billing_key", None)
            if billing_key is not None and _is_video_failed(result):
                from app.control.billing.service import get_billing_service
                svc = get_billing_service()
                if svc is not None:
                    try:
                        refunded = await svc.refund_failed_request(video_id)
                        if refunded > 0:
                            logger.info("Refunded ${} for failed video retrieve task {}", refunded, video_id)
                    except Exception as refund_exc:
                        logger.warning("Failed to refund for retrieve task {}: {}", video_id, refund_exc)
            return JSONResponse(result)
        except Exception as exc:
            logger.debug("newapi video_query fallback failed: id={} error={}", video_id, exc)

    raise ValidationError(f"Video {video_id!r} not found", param="video_id")


@router.get(
    "/videos/{video_id}/content",
    tags=[_TAG_VIDEOS],
    dependencies=[Depends(verify_api_key)],
)
async def videos_content(video_id: str):
    from .video import content_path

    path = await content_path(video_id)
    return FileResponse(path, media_type="video/mp4", filename=f"{video_id}.mp4")


# ---------------------------------------------------------------------------
# /v1/images/edits (standalone image-edit endpoint)
# ---------------------------------------------------------------------------


@router.post(
    "/images/edits", tags=[_TAG_IMAGES], dependencies=[Depends(verify_api_key)]
)
async def image_edits(
    request: Request,
    model: Annotated[str, Form(...)],
    prompt: Annotated[str, Form(...)],
    image: Annotated[list[UploadFile] | None, File(alias="image[]")] = None,
    mask: Annotated[UploadFile | None, File()] = None,
    n: Annotated[int, Form()] = 1,
    size: Annotated[str, Form()] = "1024x1024",
    response_format: Annotated[str, Form()] = "url",
    quality: Annotated[str | None, Form()] = None,
    output_format: Annotated[str | None, Form()] = None,
    background: Annotated[str | None, Form()] = None,
    output_compression: Annotated[int | None, Form()] = None,
):
    import asyncio, time as _time

    billing_key = getattr(request.state, "billing_key", None)
    _start = _time.monotonic()

    spec = model_registry.get(model)

    # ── NewAPI Fallback for third-party image-edit models (GPT Image 2) ──
    if spec is None or not spec.enabled or not spec.is_image_edit():
        from app.control.provider.newapi import is_newapi_enabled, image_edits as newapi_img_edit

        if not is_newapi_enabled():
            raise ValidationError(
                f"Model {model!r} is not an image-edit model", param="model"
            )

        # Convert uploaded images to data URIs
        images_b64: list[str] = []
        if image:
            for f in image[:16]:
                data_uri = await _upload_to_data_uri(f, param="image")
                images_b64.append(data_uri)

        result = await newapi_img_edit(
            model=model,
            prompt=prompt,
            images_b64=images_b64 or None,
            n=n,
            size=size,
            response_format=response_format,
            quality=quality,
            output_format=output_format,
            background=background,
            output_compression=output_compression,
        )

        if billing_key is not None:
            from app.control.billing.service import get_billing_service
            svc = get_billing_service()
            if svc is not None:
                duration_ms = int((_time.monotonic() - _start) * 1000)
                asyncio.create_task(
                    svc.record_usage(
                        billing_key,
                        model=model,
                        endpoint="image_edit",
                        request_id=str(result.get("created", "")),
                        duration_ms=duration_ms,
                    )
                )

        return JSONResponse(result)

    # ── Grok native path ─────────────────────────────────────────────
    if not image:
        raise ValidationError("image is required for native image edit", param="image")
    if mask is not None:
        raise ValidationError("mask is not supported yet", param="mask")
    _validate_image_edit_n(n, param="n")

    from .images import edit as img_edit

    image_inputs = [
        await _upload_to_data_uri(item, param=f"image.{index}")
        for index, item in enumerate(image)
    ]
    # Wrap input into a single-message conversation.
    content = [{"type": "text", "text": prompt}]
    content.extend(
        {"type": "image_url", "image_url": {"url": image_input}}
        for image_input in image_inputs
    )
    messages = [{"role": "user", "content": content}]
    result = await img_edit(
        model=model,
        messages=messages,
        n=n,
        size=size,
        response_format=response_format,
        stream=False,
        chat_format=False,
    )

    if billing_key is not None:
        from app.control.billing.service import get_billing_service
        svc = get_billing_service()
        if svc is not None:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            asyncio.create_task(
                svc.record_usage(
                    billing_key,
                    model=model,
                    endpoint="image_edit",
                    duration_ms=duration_ms,
                )
            )

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# /v1/files/image — serve locally saved images
# ---------------------------------------------------------------------------


@router.get("/files/video", tags=[_TAG_FILES])
async def serve_video(id: str = Query(..., description="Video file ID")):
    """Serve a locally cached video by file ID."""
    import re

    if not re.fullmatch(r"[0-9a-zA-Z_\-]{8,64}", id):
        raise ValidationError("Invalid file ID", param="id")

    path = video_files_dir() / f"{id}.mp4"
    if path.exists():
        return FileResponse(path, media_type="video/mp4")

    raise ValidationError(f"Video {id!r} not found", param="id")


@router.get("/files/image", tags=[_TAG_FILES])
async def serve_image(id: str = Query(..., description="Image file ID")):
    """Serve a locally cached image by file ID."""
    import re

    if not re.fullmatch(r"[0-9a-f\-]{16,36}", id):
        raise ValidationError("Invalid file ID", param="id")

    img_dir = image_files_dir()
    for ext in (".jpg", ".png"):
        path = img_dir / f"{id}{ext}"
        if path.exists():
            mime = "image/png" if ext == ".png" else "image/jpeg"
            return FileResponse(path, media_type=mime)

    raise ValidationError(f"Image {id!r} not found", param="id")


# ---------------------------------------------------------------------------
# /v1/video/generations — NewAPI third-party video models (JSON body)
# ---------------------------------------------------------------------------

_TAG_VIDEO_GEN = "NewAPI - Videos"


@router.post(
    "/video/generations",
    tags=[_TAG_VIDEO_GEN],
    dependencies=[Depends(verify_api_key)],
)
async def video_generations_create(request: Request):
    """Submit a video generation task to the NewAPI relay.

    Accepts any JSON body and passes it through unchanged.  Supports models
    like omni-flash, omni-flash-vref, etc.  Returns the task submission response
    (typically contains ``task_id``).
    """
    import asyncio, time as _time

    from app.control.provider.newapi import is_newapi_enabled, video_generations as newapi_video

    if not is_newapi_enabled():
        return JSONResponse(
            {"error": {"message": "NewAPI provider is not enabled", "type": "invalid_request_error"}},
            status_code=400,
        )

    billing_key = getattr(request.state, "billing_key", None)
    _start = _time.monotonic()

    body = await request.json()
    model = body.get("model", "unknown")

    # Pre-hold for video billing (use default video pricing)
    held_amount = 0.0
    if billing_key is not None:
        from app.control.billing.service import get_billing_service
        from app.control.billing.pricing import get_pricing

        svc = get_billing_service()
        if svc is not None:
            pricing = get_pricing(model)
            if pricing.per_request > 0:
                held_amount = pricing.per_request
            elif pricing.is_video:
                from app.control.billing.pricing import video_cost
                duration = body.get("duration") or body.get("seconds") or 6
                raw_res = str(body.get("resolution") or "").strip().lower() or model.lower()
                if "1080" in raw_res:
                    res = "1080p"
                elif "480" in raw_res:
                    res = "480p"
                else:
                    res = "720p"
                try:
                    video_sec = int(duration)
                except (ValueError, TypeError):
                    video_sec = 6
                held_amount = video_cost(video_sec, resolution=res, model=model)
            else:
                # Fallback: use per_request from newapi config
                from app.platform.config.snapshot import get_config as _cfg
                held_amount = _cfg().get_float("providers.newapi.default_image_price", 0.04)

            if held_amount > 0:
                ok = await svc.hold_balance(billing_key.key, held_amount)
                if not ok:
                    return JSONResponse(
                        {"error": {"message": "Insufficient balance", "type": "billing_error", "code": "insufficient_balance"}},
                        status_code=402,
                    )

    try:
        result = await newapi_video(body=body)
    except Exception as exc:
        # Refund hold on failure
        if held_amount > 0 and billing_key is not None:
            from app.control.billing.service import get_billing_service
            svc = get_billing_service()
            if svc is not None:
                await svc.refund_hold(billing_key.key, held_amount)
        logger.exception("newapi video proxy failed: model={} error={}", model, exc)
        return JSONResponse(
            {"error": {"message": sanitize_exception(exc), "type": "server_error"}},
            status_code=502,
        )

    # Register pending video hold for settlement upon poll completion
        task_id = result.get("task_id") or result.get("id") or ""
        if not task_id and isinstance(result.get("data"), dict):
            task_id = result.get("data").get("task_id") or result.get("data").get("id") or ""

        if billing_key is not None and held_amount > 0 and task_id:
            duration_val = body.get("duration") or body.get("seconds") or 6
            try:
                video_sec = int(duration_val)
            except (ValueError, TypeError):
                video_sec = 6
            raw_res = str(body.get("resolution") or "").strip().lower() or model.lower()
            if "1080" in raw_res:
                video_res = "1080p"
            elif "480" in raw_res:
                video_res = "480p"
            else:
                video_res = "720p"

            hold_entry = _PendingVideoHold(
                key_record=billing_key,
                model=model,
                video_seconds=video_sec,
                video_resolution=video_res,
                held_amount=held_amount,
                created_at=_time.monotonic(),
            )
            async with _PENDING_VIDEO_HOLDS_LOCK:
                _PENDING_VIDEO_HOLDS[str(task_id)] = hold_entry
                if ":" in str(task_id):
                    _PENDING_VIDEO_HOLDS[str(task_id).split(":", 1)[1]] = hold_entry
            asyncio.create_task(_cleanup_stale_video_holds())

    return JSONResponse(result)


def _is_video_failed(res: Any) -> bool:
    """Check if the video generation task result indicates failure."""
    if not isinstance(res, dict):
        return False
    if "error" in res or "err" in res:
        return True

    # Check status
    status = str(res.get("status") or "").lower()
    if status in ("failed", "error", "fail"):
        return True

    nested_data = res.get("data")
    if isinstance(nested_data, dict):
        if "error" in nested_data or "err" in nested_data:
            return True
        status = str(nested_data.get("status") or "").lower()
        if status in ("failed", "error", "fail"):
            return True

    return False


@router.get(
    "/video/generations/{task_id}",
    tags=[_TAG_VIDEO_GEN],
    dependencies=[Depends(verify_api_key)],
)
async def video_generations_poll(task_id: str, request: Request):
    """Poll the status of a video generation task from the NewAPI relay."""
    from app.control.provider.newapi import is_newapi_enabled, video_generations_poll as newapi_poll

    if not is_newapi_enabled():
        return JSONResponse(
            {"error": {"message": "NewAPI provider is not enabled", "type": "invalid_request_error"}},
            status_code=400,
        )

    try:
        result = await newapi_poll(task_id)
        await _process_pending_video_hold(task_id, result)
    except Exception as exc:
        logger.exception("newapi video poll failed: task_id={} error={}", task_id, exc)
        return JSONResponse(
            {"error": {"message": sanitize_exception(exc), "type": "server_error"}},
            status_code=502,
        )

    billing_key = getattr(request.state, "billing_key", None)
    if billing_key is not None and _is_video_failed(result):
        from app.control.billing.service import get_billing_service
        svc = get_billing_service()
        if svc is not None:
            try:
                refunded = await svc.refund_failed_request(task_id)
                if refunded > 0:
                    logger.info("Refunded ${} for failed video task {}", refunded, task_id)
            except Exception as refund_exc:
                logger.warning("Failed to refund for task {}: {}", task_id, refund_exc)

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# /v1/video/create + /v1/video/query — third-party GROK video models
# ---------------------------------------------------------------------------

_TAG_VIDEO_CREATE = "Third-Party - Videos"


@router.post(
    "/video/create",
    tags=[_TAG_VIDEO_CREATE],
    dependencies=[Depends(verify_api_key)],
)
async def video_create_endpoint(request: Request):
    """Unified video creation endpoint for third-party GROK video models.

    Accepts JSON body with model, prompt, aspect_ratio, size, seconds, images.
    Routes to the NewAPI relay's /v1/video/create interface.
    """
    import asyncio, time as _time

    from app.control.provider.newapi import is_newapi_enabled, video_create as newapi_video_create

    if not is_newapi_enabled():
        return JSONResponse(
            {"error": {"message": "NewAPI provider is not enabled", "type": "invalid_request_error"}},
            status_code=400,
        )

    billing_key = getattr(request.state, "billing_key", None)
    _start = _time.monotonic()
    body = await request.json()
    model = body.get("model", "unknown")

    # Standardize image references
    urls = await _extract_images_from_payload(body)
    _standardize_newapi_video_body(body, urls)

    # Pre-hold billing check
    held_amount = 0.0
    if billing_key is not None:
        from app.control.billing.service import get_billing_service
        from app.control.billing.pricing import get_pricing, video_cost

        svc = get_billing_service()
        if svc is not None:
            pricing = get_pricing(model)
            if pricing.per_request > 0:
                held_amount = pricing.per_request
            elif pricing.is_video:
                raw_size = str(body.get("size", "")).strip().lower()
                if raw_size in ("480p", "sd"):
                    video_res = "480p"
                else:
                    video_res = "720p"
                try:
                    video_sec = int(body.get("seconds", 6))
                except (ValueError, TypeError):
                    video_sec = 6
                held_amount = video_cost(video_sec, resolution=video_res, model=model)
            else:
                held_amount = 0.04

            if held_amount > 0:
                ok = await svc.hold_balance(billing_key.key, held_amount)
                if not ok:
                    return JSONResponse(
                        {
                            "error": {
                                "message": "Insufficient balance",
                                "type": "billing_error",
                                "code": "insufficient_balance",
                            }
                        },
                        status_code=402,
                    )

    try:
        result = await newapi_video_create(body=body)
    except Exception as exc:
        if held_amount > 0 and billing_key is not None:
            from app.control.billing.service import get_billing_service
            svc = get_billing_service()
            if svc is not None:
                await svc.refund_hold(billing_key.key, held_amount)
        logger.exception("newapi video_create failed: model={} error={}", model, exc)
        return JSONResponse(
            {"error": {"message": sanitize_exception(exc), "type": "server_error"}},
            status_code=502,
        )

    # Register pending video hold for settlement upon poll completion
    task_id = result.get("id") or result.get("task_id") or ""
    if not task_id and isinstance(result.get("data"), dict):
        task_id = result.get("data").get("id") or result.get("data").get("task_id") or ""

    if billing_key is not None and held_amount > 0 and task_id:
        try:
            video_sec = int(body.get("seconds", 6))
        except (ValueError, TypeError):
            video_sec = 6
        raw_size = str(body.get("size", "")).strip().lower()
        video_res = "480p" if raw_size in ("480p", "sd") else "720p"

        hold_entry = _PendingVideoHold(
            key_record=billing_key,
            model=model,
            video_seconds=video_sec,
            video_resolution=video_res,
            held_amount=held_amount,
            created_at=_time.monotonic(),
        )
        async with _PENDING_VIDEO_HOLDS_LOCK:
            _PENDING_VIDEO_HOLDS[str(task_id)] = hold_entry
            if ":" in str(task_id):
                _PENDING_VIDEO_HOLDS[str(task_id).split(":", 1)[1]] = hold_entry
        asyncio.create_task(_cleanup_stale_video_holds())

    return JSONResponse(result)


@router.get(
    "/video/query",
    tags=[_TAG_VIDEO_CREATE],
    dependencies=[Depends(verify_api_key)],
)
async def video_query_endpoint(
    request: Request,
    id: str = Query(..., description="Video task ID"),
):
    """Query the status of a third-party video generation task.

    Uses GET /v1/video/query?id={VIDEO_ID} on the NewAPI relay.
    """
    from app.control.provider.newapi import is_newapi_enabled, video_query as newapi_video_query

    if not is_newapi_enabled():
        return JSONResponse(
            {"error": {"message": "NewAPI provider is not enabled", "type": "invalid_request_error"}},
            status_code=400,
        )

    try:
        result = await newapi_video_query(id)
        await _process_pending_video_hold(id, result)
    except Exception as exc:
        logger.exception("newapi video_query failed: id={} error={}", id, exc)
        return JSONResponse(
            {"error": {"message": sanitize_exception(exc), "type": "server_error"}},
            status_code=502,
        )

    billing_key = getattr(request.state, "billing_key", None)
    if billing_key is not None and _is_video_failed(result):
        from app.control.billing.service import get_billing_service
        svc = get_billing_service()
        if svc is not None:
            try:
                refunded = await svc.refund_failed_request(id)
                if refunded > 0:
                    logger.info("Refunded ${} for failed video query task {}", refunded, id)
            except Exception as refund_exc:
                logger.warning("Failed to refund for query task {}: {}", id, refund_exc)

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# /v1/billing — user-facing billing endpoints (for dashboard.html)
# ---------------------------------------------------------------------------

_TAG_BILLING = "Billing"


@router.get("/billing/balance", tags=[_TAG_BILLING], dependencies=[Depends(verify_api_key)])
async def billing_balance(request: Request):
    """Return balance info for the authenticated billing key."""
    from app.control.billing.service import is_billing_enabled, get_billing_service

    billing_key = getattr(request.state, "billing_key", None)
    if not is_billing_enabled() or billing_key is None:
        return JSONResponse({"billing": False, "message": "Billing is not enabled or key is not a billing key."})

    return JSONResponse({
        "billing": True,
        "key_name": billing_key.name or "Anonymous",
        "group": billing_key.group or "default",
        "balance": billing_key.balance,
        "total_charged": billing_key.total_charged,
        "status": billing_key.status,
    })


@router.get("/billing/usage", tags=[_TAG_BILLING], dependencies=[Depends(verify_api_key)])
async def billing_usage(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
):
    """Return usage logs for the authenticated billing key."""
    from app.control.billing.service import is_billing_enabled, get_billing_service

    billing_key = getattr(request.state, "billing_key", None)
    if not is_billing_enabled() or billing_key is None:
        return JSONResponse({"items": [], "total": 0, "summary": {}})

    svc = get_billing_service()
    if svc is None:
        return JSONResponse({"items": [], "total": 0, "summary": {}})

    items, total = await svc.get_usage(
        api_key=billing_key.key,
        page=page,
        page_size=page_size,
    )
    summary = await svc.get_usage_summary(api_key=billing_key.key)

    return JSONResponse({
        "items": [item.model_dump() for item in items],
        "total": total,
        "summary": summary,
    })


__all__ = ["router"]

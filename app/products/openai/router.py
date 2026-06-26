"""OpenAI-compatible API router (/v1/*)."""

import base64
import binascii
import mimetypes
from typing import Annotated, AsyncGenerator, AsyncIterable, Literal

import orjson
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from app.control.account.state_machine import is_manageable
from app.platform.auth.middleware import verify_api_key
from app.platform.errors import AppError, ValidationError
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
        if _model_available_for_pools(m, pools)
    ]

    # Merge NewAPI upstream models if enabled
    from app.control.provider.newapi import is_newapi_enabled, list_models as newapi_list

    if is_newapi_enabled() and _cfg().get_bool("providers.newapi.merge_models", True):
        local_ids = {m["id"] for m in models}
        try:
            upstream = await newapi_list()
            for um in upstream:
                if um.get("id") not in local_ids:
                    models.append(um)
        except Exception as exc:
            logger.debug("newapi model merge skipped: error={}", exc)

    return JSONResponse({"object": "list", "data": models})


@router.get(
    "/models/{model_id}", tags=[_TAG_MODELS], dependencies=[Depends(verify_api_key)]
)
async def get_model_endpoint(model_id: str, request: Request):
    import time

    spec = model_registry.get(model_id)
    pools = await _available_pools(request)
    if spec is None or not _model_available_for_pools(spec, pools):
        return JSONResponse(
            {
                "error": {
                    "message": f"Model {model_id!r} not found",
                    "type": "invalid_request_error",
                }
            },
            status_code=404,
        )
    return JSONResponse(
        {
            "id": spec.model_name,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "xai",
            "name": spec.public_name,
        }
    )


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
            {"error": {"message": str(exc), "type": "server_error"}}
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
                "message": str(exc),
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
async def videos_create(
    request: Request,
    model: Annotated[str, Form(...)],
    prompt: Annotated[str, Form(...)],
    seconds: Annotated[int | str, Form()] = 6,
    size: Annotated[str, Form()] = "720x1280",
    resolution_name: Annotated[str | None, Form()] = None,
    preset: Annotated[
        Literal["fun", "normal", "spicy", "custom"] | None, Form()
    ] = None,
    input_reference: Annotated[
        list[UploadFile] | None, File(alias="input_reference[]")
    ] = None,
    aspect_ratio: Annotated[str | None, Form()] = None,
    resolution: Annotated[str | None, Form()] = None,
):
    import asyncio, time as _time

    billing_key = getattr(request.state, "billing_key", None)

    # ── NewAPI Fallback: third-party video models ────────────────────
    from app.control.provider.newapi import (
        is_newapi_enabled, is_third_party_video_model, video_create as newapi_video_create,
    )

    if is_third_party_video_model(model) and is_newapi_enabled():
        # Build JSON body for /v1/video/create
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "seconds": str(seconds),
        }
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        elif size and ":" in str(size):
            # size could be "16:9" style aspect ratio
            body["aspect_ratio"] = str(size)
        elif size:
            body["size"] = str(size)
        if resolution_name:
            body["size"] = resolution_name.upper()  # "720p" → "720P"
        elif resolution:
            body["size"] = resolution.upper()

        # Collect reference images
        ref_urls: list[str] = []
        if input_reference:
            for f in input_reference[:7]:
                data_uri = await _upload_to_data_uri(f, param="input_reference")
                ref_urls.append(data_uri)
        if ref_urls:
            body["images"] = ref_urls
        else:
            body["images"] = []

        _start = _time.monotonic()
        try:
            result = await newapi_video_create(body=body)
        except Exception as exc:
            logger.exception(
                "newapi video_create proxy failed: model={} error={}", model, exc,
            )
            return JSONResponse(
                {"error": {"message": str(exc), "type": "server_error"}},
                status_code=502,
            )

        # Billing
        if billing_key is not None:
            from app.control.billing.service import get_billing_service
            svc = get_billing_service()
            if svc is not None:
                duration_ms = int((_time.monotonic() - _start) * 1000)
                task_id = result.get("id") or result.get("task_id") or ""
                asyncio.create_task(
                    svc.record_usage(
                        billing_key,
                        model=model,
                        endpoint="video",
                        request_id=str(task_id),
                        duration_ms=duration_ms,
                    )
                )

        return JSONResponse(result)

    # ── Grok native path ─────────────────────────────────────────────
    from .video import create_video

    references_payload = None
    if input_reference:
        references_payload = [
            {"image_url": await _upload_to_data_uri(f, param="input_reference")}
            for f in input_reference[:7]
        ]

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
async def videos_retrieve(video_id: str):
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
                duration = body.get("duration", 6)
                held_amount = video_cost(int(duration) if duration else 6)
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
            {"error": {"message": str(exc), "type": "server_error"}},
            status_code=502,
        )

    # Record billing on successful submission
    if billing_key is not None:
        from app.control.billing.service import get_billing_service
        svc = get_billing_service()
        if svc is not None:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            task_id = result.get("task_id") or result.get("id") or ""
            asyncio.create_task(
                svc.record_usage(
                    billing_key,
                    model=model,
                    endpoint="video",
                    request_id=str(task_id),
                    duration_ms=duration_ms,
                    held_amount=held_amount,
                )
            )

    return JSONResponse(result)


@router.get(
    "/video/generations/{task_id}",
    tags=[_TAG_VIDEO_GEN],
    dependencies=[Depends(verify_api_key)],
)
async def video_generations_poll(task_id: str):
    """Poll the status of a video generation task from the NewAPI relay."""
    from app.control.provider.newapi import is_newapi_enabled, video_generations_poll as newapi_poll

    if not is_newapi_enabled():
        return JSONResponse(
            {"error": {"message": "NewAPI provider is not enabled", "type": "invalid_request_error"}},
            status_code=400,
        )

    try:
        result = await newapi_poll(task_id)
    except Exception as exc:
        logger.exception("newapi video poll failed: task_id={} error={}", task_id, exc)
        return JSONResponse(
            {"error": {"message": str(exc), "type": "server_error"}},
            status_code=502,
        )

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

    try:
        result = await newapi_video_create(body=body)
    except Exception as exc:
        logger.exception("newapi video_create failed: model={} error={}", model, exc)
        return JSONResponse(
            {"error": {"message": str(exc), "type": "server_error"}},
            status_code=502,
        )

    # Billing
    if billing_key is not None:
        from app.control.billing.service import get_billing_service
        svc = get_billing_service()
        if svc is not None:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            task_id = result.get("id") or result.get("task_id") or ""
            asyncio.create_task(
                svc.record_usage(
                    billing_key,
                    model=model,
                    endpoint="video",
                    request_id=str(task_id),
                    duration_ms=duration_ms,
                )
            )

    return JSONResponse(result)


@router.get(
    "/video/query",
    tags=[_TAG_VIDEO_CREATE],
    dependencies=[Depends(verify_api_key)],
)
async def video_query_endpoint(
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
    except Exception as exc:
        logger.exception("newapi video_query failed: id={} error={}", id, exc)
        return JSONResponse(
            {"error": {"message": str(exc), "type": "server_error"}},
            status_code=502,
        )

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

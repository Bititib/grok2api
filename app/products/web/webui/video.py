"""WebUI video generation endpoint backed by Grok video pipeline via WebSocket.

Supports concurrent batch generation: the client sends multiple ``start``
messages within a single WebSocket session, each spawning an independent
generation task identified by its ``run_id``.
"""

import asyncio
import hmac
import uuid
from typing import Optional

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.platform.auth.middleware import get_webui_key, is_webui_enabled
from app.platform.logging.logger import logger

router = APIRouter()

# Maximum concurrent video generation tasks per WebSocket connection.
_MAX_CONCURRENT_TASKS = 8


def _extract_token(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    scheme, _, token = raw.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return raw


def _is_allowed(token: str) -> bool:
    webui_key = get_webui_key()
    if not webui_key:
        return is_webui_enabled()
    return bool(token) and hmac.compare_digest(token, webui_key)


def _websocket_token(websocket: WebSocket) -> str:
    return (
        _extract_token(websocket.headers.get("authorization"))
        or str(websocket.query_params.get("access_token") or "").strip()
    )


@router.websocket("/video/ws")
async def video_ws(websocket: WebSocket):
    if not _is_allowed(_websocket_token(websocket)):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # Track all active tasks by run_id.
    active_tasks: dict[str, asyncio.Task] = {}
    send_lock = asyncio.Lock()
    connection_alive = True

    async def _send(payload: dict) -> bool:
        nonlocal connection_alive
        if not connection_alive:
            return False
        try:
            async with send_lock:
                await websocket.send_text(orjson.dumps(payload).decode())
            return True
        except Exception:
            # Connection is dead — cancel all running tasks to stop the flood
            connection_alive = False
            for task in active_tasks.values():
                if not task.done():
                    task.cancel()
            return False

    async def _stop_task(run_id: str) -> None:
        task = active_tasks.pop(run_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass

    async def _stop_all() -> None:
        ids = list(active_tasks.keys())
        for rid in ids:
            await _stop_task(rid)

    async def _run(
        run_id: str,
        prompt: str,
        size: str,
        seconds: int,
        preset: str,
        model: str = "grok-imagine-video",
        input_references: list[dict] | None = None,
    ):
        from app.products.openai.video import (
            _run_video_generation,
            _resolve_video_size,
            _resolve_video_resolution_name,
            _resolve_video_preset,
            validate_video_length,
            _download_video_bytes,
            _save_video_bytes,
            _local_video_url,
        )

        await _send({
            "type": "status",
            "status": "running",
            "prompt": prompt,
            "size": size,
            "seconds": seconds,
            "preset": preset,
            "model": model,
            "run_id": run_id,
        })

        try:
            validate_video_length(seconds)
            aspect_ratio, default_res = _resolve_video_size(size)
            resolution_name = _resolve_video_resolution_name(None, default=default_res)
            resolved_preset = _resolve_video_preset(preset)

            async def _progress_cb(progress: int) -> None:
                if not connection_alive:
                    return
                await _send({
                    "type": "progress",
                    "progress": max(0, min(100, progress)),
                    "run_id": run_id,
                })

            artifact = await _run_video_generation(
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution_name=resolution_name,
                seconds=seconds,
                preset=resolved_preset,
                input_references=input_references,
                progress_cb=_progress_cb,
            )

            # 下载视频到本地缓存，返回本地 URL
            video_url = artifact.video_url
            try:
                import hashlib
                file_id = hashlib.sha1(video_url.encode("utf-8")).hexdigest()[:32]
                # _download_video_bytes needs a token; get one from account directory
                from app.dataplane.account import _directory as _acct_dir
                if _acct_dir is not None:
                    acct = await _acct_dir.reserve(
                        pool_candidates=None,
                        mode_id=0,
                        now_s_override=None,
                    )
                    if acct:
                        try:
                            raw, _mime = await _download_video_bytes(acct.token, video_url)
                            import asyncio as _aio
                            await _aio.to_thread(_save_video_bytes, raw, file_id)
                            video_url = _local_video_url(file_id)
                        finally:
                            await _acct_dir.release(acct)
            except Exception as dl_exc:
                logger.debug("webui video local cache failed, using upstream url: {}", dl_exc)

            await _send({
                "type": "video",
                "url": video_url,
                "thumbnail_url": artifact.thumbnail_url or "",
                "run_id": run_id,
            })

            await _send({
                "type": "status",
                "status": "completed",
                "run_id": run_id,
            })
        except asyncio.CancelledError:
            await _send({"type": "status", "status": "stopped", "run_id": run_id})
        except Exception as exc:
            logger.error(
                "webui video run failed: run_id={} error_type={} error={}",
                run_id,
                type(exc).__name__,
                exc,
            )
            await _send({
                "type": "error",
                "message": str(exc),
                "code": "internal_error",
                "run_id": run_id,
            })
        finally:
            active_tasks.pop(run_id, None)

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except (RuntimeError, WebSocketDisconnect):
                break

            try:
                payload = orjson.loads(raw)
            except Exception:
                await _send({
                    "type": "error",
                    "message": "Invalid message format.",
                    "code": "invalid_payload",
                })
                continue

            action = payload.get("type")
            if action == "start":
                prompt = str(payload.get("prompt") or "").strip()
                if not prompt:
                    await _send({
                        "type": "error",
                        "message": "Prompt cannot be empty.",
                        "code": "invalid_prompt",
                    })
                    continue

                # Enforce per-connection concurrency limit.
                running_count = sum(1 for t in active_tasks.values() if not t.done())
                if running_count >= _MAX_CONCURRENT_TASKS:
                    await _send({
                        "type": "error",
                        "message": f"Too many concurrent tasks (max {_MAX_CONCURRENT_TASKS}).",
                        "code": "too_many_tasks",
                    })
                    continue

                size = str(payload.get("size") or "720x1280").strip()
                try:
                    seconds = int(payload.get("seconds") or 6)
                except (TypeError, ValueError):
                    seconds = 6
                preset = str(payload.get("preset") or "custom").strip().lower()
                if preset not in {"fun", "normal", "spicy", "custom"}:
                    preset = "custom"

                # Support both single and multi reference images
                input_references = None
                refs_data = payload.get("input_references")
                if isinstance(refs_data, list):
                    input_references = [
                        {"image_url": str(r["image_url"])}
                        for r in refs_data
                        if isinstance(r, dict) and r.get("image_url")
                    ] or None
                else:
                    ref_data = payload.get("input_reference")
                    if isinstance(ref_data, dict) and ref_data.get("image_url"):
                        input_references = [{"image_url": str(ref_data["image_url"])}]

                # Allowed video models for WebUI.
                _ALLOWED_MODELS = {"grok-imagine-video", "grok-4.3-video", "grok-4.3-video-heavy"}
                model = str(payload.get("model") or "grok-imagine-video").strip()
                if model not in _ALLOWED_MODELS:
                    model = "grok-imagine-video"

                # Client may supply a run_id; otherwise generate one.
                run_id = str(payload.get("run_id") or "").strip() or uuid.uuid4().hex

                task = asyncio.create_task(_run(run_id, prompt, size, seconds, preset, model, input_references))
                active_tasks[run_id] = task
                continue

            if action == "stop":
                target_run_id = str(payload.get("run_id") or "").strip()
                if target_run_id:
                    await _stop_task(target_run_id)
                else:
                    await _stop_all()
                continue

            if action == "ping":
                # Client heartbeat — keep connection alive, no response needed
                continue

            await _send({
                "type": "error",
                "message": "Unknown action.",
                "code": "invalid_action",
            })
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(
            "webui video websocket handler failed: error_type={} error={}",
            type(exc).__name__,
            exc,
        )
    finally:
        await _stop_all()
        try:
            from starlette.websockets import WebSocketState
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close(code=1000, reason="Server closing connection")
        except Exception:
            pass

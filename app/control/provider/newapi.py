"""NewAPI (One API) transparent proxy adapter.

Forwards requests to a NewAPI-compatible relay station for models not
registered in the local Grok model registry.  Supports:

  - ``/v1/chat/completions``   (streaming + non-streaming)
  - ``/v1/images/generations`` (non-streaming)
  - ``/v1/models``             (model list merge)

Uses ``aiohttp`` (already a project dependency) for HTTP transport.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import aiohttp
import orjson

from app.platform.config.snapshot import get_config
from app.platform.logging.logger import logger


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def is_newapi_enabled() -> bool:
    """Check if the NewAPI relay is enabled and properly configured."""
    cfg = get_config()
    if not cfg.get_bool("providers.newapi.enabled", False):
        return False
    base_url = cfg.get_str("providers.newapi.base_url", "").strip()
    api_key = cfg.get_str("providers.newapi.api_key", "").strip()
    return bool(base_url and api_key)


def _get_newapi_config() -> tuple[str, str, float]:
    """Return (base_url, api_key, timeout) for the NewAPI relay."""
    cfg = get_config()
    base_url = cfg.get_str("providers.newapi.base_url", "").strip().rstrip("/")
    api_key = cfg.get_str("providers.newapi.api_key", "").strip()
    timeout = cfg.get_float("providers.newapi.timeout", 120.0)
    return base_url, api_key, timeout


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Upstream status — balance & connectivity check
# ---------------------------------------------------------------------------

async def get_upstream_status() -> dict[str, Any]:
    """Query the NewAPI relay for its balance and connectivity status.

    Tries multiple common NewAPI / One API endpoints:
      1. ``/api/user/self``  → user profile including ``quota``
      2. ``/api/status``     → system status
      3. ``/v1/models``      → fallback connectivity check

    Returns a dict with keys: connected, balance, quota, models_count, error.
    """
    if not is_newapi_enabled():
        return {"connected": False, "error": "NewAPI is not enabled"}

    base_url, api_key, timeout = _get_newapi_config()
    result: dict[str, Any] = {
        "connected": False,
        "base_url": base_url,
        "balance": None,
        "quota": None,
        "username": None,
        "models_count": 0,
        "error": None,
    }

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=min(timeout, 10))
        ) as session:
            # Try /api/user/self (New API / One API standard)
            try:
                async with session.get(
                    f"{base_url}/api/user/self",
                    headers=_headers(api_key),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        data = body.get("data", {})
                        if isinstance(data, dict):
                            result["quota"] = data.get("quota")
                            result["username"] = data.get("username") or data.get("display_name")
                            # NewAPI quota is in units of 1/500000 USD
                            quota = data.get("quota")
                            if quota is not None:
                                result["balance"] = round(quota / 500000, 4)
                            result["connected"] = True
            except Exception:
                pass

            # Try /api/status as fallback
            if not result["connected"]:
                try:
                    async with session.get(
                        f"{base_url}/api/status",
                        headers=_headers(api_key),
                    ) as resp:
                        if resp.status == 200:
                            result["connected"] = True
                except Exception:
                    pass

            # Count models
            try:
                async with session.get(
                    f"{base_url}/v1/models",
                    headers=_headers(api_key),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        models = body.get("data", [])
                        result["models_count"] = len(models) if isinstance(models, list) else 0
                        result["connected"] = True
            except Exception:
                pass

    except Exception as exc:
        result["error"] = str(exc)

    if not result["connected"] and not result["error"]:
        result["error"] = "Unable to connect to NewAPI relay"

    return result


# ---------------------------------------------------------------------------
# /v1/models — list upstream models
# ---------------------------------------------------------------------------

async def list_models() -> list[dict[str, Any]]:
    """Fetch the model list from the NewAPI relay station."""
    if not is_newapi_enabled():
        return []

    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/models"

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=min(timeout, 15))
        ) as session:
            async with session.get(url, headers=_headers(api_key)) as resp:
                resp.raise_for_status()
                body = await resp.json()
    except Exception as exc:
        logger.debug("newapi list_models failed: error={}", exc)
        return []

    data = body.get("data", [])
    if not isinstance(data, list):
        return []

    return [
        {
            "id": m.get("id", ""),
            "object": "model",
            "created": m.get("created", int(time.time())),
            "owned_by": m.get("owned_by", "newapi"),
            "name": m.get("id", ""),
        }
        for m in data
        if isinstance(m, dict) and m.get("id")
    ]


# ---------------------------------------------------------------------------
# /v1/chat/completions — transparent proxy
# ---------------------------------------------------------------------------

async def chat_completions(
    *,
    model: str,
    messages: list[dict[str, Any]],
    stream: bool = False,
    temperature: float = 0.8,
    top_p: float = 0.95,
    tools: list[dict] | None = None,
    tool_choice: Any = None,
    **kwargs: Any,
) -> dict[str, Any] | AsyncGenerator[str, None]:
    """Forward a chat completion request to the NewAPI relay.

    Returns:
      - Non-streaming: the full JSON response dict
      - Streaming: an async generator yielding raw SSE lines
    """
    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/chat/completions"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "top_p": top_p,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice

    # Forward any extra kwargs (max_tokens, etc.)
    for key, value in kwargs.items():
        if value is not None and key not in payload:
            payload[key] = value

    logger.info(
        "newapi chat proxy: model={} stream={} url={}",
        model, stream, url,
    )

    if stream:
        # Ask upstream to include usage in the final SSE chunk
        payload.setdefault("stream_options", {"include_usage": True})
        return _stream_chat(url, payload, api_key, timeout)
    else:
        return await _sync_chat(url, payload, api_key, timeout)


async def _sync_chat(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    """Non-streaming chat completion."""
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(url, json=payload, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            return await resp.json()


@dataclass
class StreamWithUsage:
    """Async SSE generator wrapper that collects usage from the final chunk.

    Usage pattern:
        sw = _stream_chat(...)   # returns StreamWithUsage
        async for line in sw:    # iterate SSE lines
            ...
        print(sw.usage)          # {"prompt_tokens": N, "completion_tokens": M, ...}
    """

    _gen: Any = field(repr=False)
    usage: dict[str, Any] = field(default_factory=dict)

    def __aiter__(self):
        return self._iter()

    async def _iter(self) -> AsyncGenerator[str, None]:
        async for line in self._gen:
            # Try to extract usage from SSE data lines
            if line.startswith("data: ") and "usage" in line:
                try:
                    data_str = line[6:].strip()
                    if data_str and data_str != "[DONE]":
                        chunk = orjson.loads(data_str)
                        u = chunk.get("usage")
                        if isinstance(u, dict) and u.get("total_tokens"):
                            self.usage = u
                except Exception:
                    pass
            yield line


def _stream_chat(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: float,
) -> StreamWithUsage:
    """Streaming chat completion — returns StreamWithUsage that collects usage."""

    async def _gen() -> AsyncGenerator[str, None]:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.post(url, json=payload, headers=_headers(api_key)) as resp:
                resp.raise_for_status()
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line:
                        yield f"{line}\n\n"

    return StreamWithUsage(_gen=_gen())


# ---------------------------------------------------------------------------
# /v1/images/generations — transparent proxy
# ---------------------------------------------------------------------------

async def image_generations(
    *,
    model: str,
    prompt: str,
    n: int = 1,
    size: str = "1024x1024",
    response_format: str = "url",
    **kwargs: Any,
) -> dict[str, Any]:
    """Forward an image generation request to the NewAPI relay."""
    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/images/generations"

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "response_format": response_format,
    }
    for key, value in kwargs.items():
        if value is not None and key not in payload:
            payload[key] = value

    logger.info("newapi image proxy: model={} url={}", model, url)

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(url, json=payload, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            return await resp.json()


# ---------------------------------------------------------------------------
# /v1/images/edits — transparent proxy
# ---------------------------------------------------------------------------

async def image_edits(
    *,
    model: str,
    prompt: str,
    images_b64: list[str] | None = None,
    n: int = 1,
    size: str = "1024x1024",
    response_format: str = "url",
    **kwargs: Any,
) -> dict[str, Any]:
    """Forward an image edit request to the NewAPI relay.

    Supports multiple reference images (up to 16) and GPT Image 2 extra
    parameters (quality, output_format, background, etc.) via **kwargs.
    """
    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/images/edits"

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "response_format": response_format,
    }
    # Attach reference images — GPT Image 2 accepts "images" array
    if images_b64:
        if len(images_b64) == 1:
            payload["image"] = images_b64[0]
        else:
            payload["images"] = [{"image_url": img} for img in images_b64]

    # Forward extra params (quality, output_format, background, etc.)
    for key, value in kwargs.items():
        if value is not None and key not in payload:
            payload[key] = value

    logger.info("newapi image_edit proxy: model={} n_images={} url={}", model, len(images_b64 or []), url)

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(url, json=payload, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            return await resp.json()


# ---------------------------------------------------------------------------
# /v1/video/generations — transparent proxy (submit + poll)
# ---------------------------------------------------------------------------

async def video_generations(
    *,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Forward a video generation request to the NewAPI relay.

    Accepts the raw JSON body from the client and passes it through unchanged.
    This supports all NewAPI video models (omni-flash, omni-flash-vref, etc.)
    with their specific fields (model, prompt, duration, aspect_ratio, images,
    video, etc.).
    """
    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/video/generations"

    logger.info(
        "newapi video proxy: model={} url={}",
        body.get("model", "?"), url,
    )

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(url, json=body, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            return await resp.json()


async def video_generations_poll(task_id: str) -> dict[str, Any]:
    """Poll the status of a video generation task from the NewAPI relay."""
    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/video/generations/{task_id}"

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=min(timeout, 30))
    ) as session:
        async with session.get(url, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            return await resp.json()


# ---------------------------------------------------------------------------
# /v1/video/create + /v1/video/query — third-party GROK video models
# ---------------------------------------------------------------------------

# Models that should be routed through the /v1/video/create + /v1/video/query
# interface rather than the standard /v1/video/generations path.
THIRD_PARTY_VIDEO_MODELS: frozenset[str] = frozenset({
    "grok-imagine-video-1.5-preview",
    "grok-imagine-1.0-video",
    "grok-imagine-video-1.5-fast",
})


def is_third_party_video_model(model: str) -> bool:
    """Check if a model should use the /v1/video/create interface."""
    return model in THIRD_PARTY_VIDEO_MODELS


async def video_create(*, body: dict[str, Any]) -> dict[str, Any]:
    """Forward a video creation request to the NewAPI relay via /v1/video/create.

    This endpoint supports the three GROK video models:
      - grok-imagine-video-1.5-preview (image-to-video, 1-15s)
      - grok-imagine-1.0-video         (text/image-to-video, 6 or 10s)
      - grok-imagine-video-1.5-fast     (text/image-to-video, 6 or 10s)

    Accepts a JSON body with fields: model, prompt, aspect_ratio, size,
    seconds, images, etc.  Passes through unchanged.
    """
    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/video/create"

    logger.info(
        "newapi video_create proxy: model={} url={}",
        body.get("model", "?"), url,
    )

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(url, json=body, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            return await resp.json()


async def video_query(video_id: str) -> dict[str, Any]:
    """Query the status of a video task via GET /v1/video/query?id={video_id}.

    Returns the full task status including progress, status, video_url, etc.
    """
    base_url, api_key, timeout = _get_newapi_config()
    url = f"{base_url}/v1/video/query"

    logger.info("newapi video_query proxy: video_id={} url={}", video_id, url)

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=min(timeout, 30))
    ) as session:
        async with session.get(
            url,
            params={"id": video_id},
            headers=_headers(api_key),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


__all__ = [
    "is_newapi_enabled",
    "get_upstream_status",
    "list_models",
    "chat_completions",
    "image_generations",
    "image_edits",
    "video_generations",
    "video_generations_poll",
    "is_third_party_video_model",
    "video_create",
    "video_query",
    "THIRD_PARTY_VIDEO_MODELS",
]

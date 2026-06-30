"""NewAPI (One API) multi-channel transparent proxy adapter.

Forwards requests to multiple NewAPI-compatible relay stations based on the
model. Supports load balancing, channel mapping, and stateless task ID routing.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import aiohttp
import orjson

from app.platform.config.snapshot import get_config
from app.platform.logging.logger import logger


@dataclass(slots=True)
class Channel:
    """Represents a single upstream NewAPI channel."""
    id: str
    name: str
    base_url: str
    api_key: str
    models: list[str]
    enabled: bool = True
    timeout: float = 120.0


# ---------------------------------------------------------------------------
# Channel Configuration & Selection
# ---------------------------------------------------------------------------

def _get_all_channels() -> list[Channel]:
    """Load all configured channels from config.toml."""
    cfg = get_config()
    channels: list[Channel] = []

    # 1. Default channel (legacy providers.newapi config)
    if cfg.get_bool("providers.newapi.enabled", False):
        base_url = cfg.get_str("providers.newapi.base_url", "").strip().rstrip("/")
        api_key = cfg.get_str("providers.newapi.api_key", "").strip()
        timeout = cfg.get_float("providers.newapi.timeout", 120.0)
        if base_url and api_key:
            channels.append(
                Channel(
                    id="default",
                    name="Default NewAPI",
                    base_url=base_url,
                    api_key=api_key,
                    models=[],  # Empty means it acts as a fallback for all models
                    enabled=True,
                    timeout=timeout,
                )
            )

    # 2. Extra channels from the new channels list
    extra_list = cfg.get("providers.newapi.channels", [])
    if isinstance(extra_list, list):
        for item in extra_list:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            cname = str(item.get("name") or cid or "Extra Channel").strip()
            enabled = bool(item.get("enabled", True))
            base_url = str(item.get("base_url") or "").strip().rstrip("/")
            api_key = str(item.get("api_key") or "").strip()
            models = [str(m).strip() for m in item.get("models", []) if m]
            timeout = float(item.get("timeout") or 120.0)

            if cid and base_url and api_key and enabled:
                channels.append(
                    Channel(
                        id=cid,
                        name=cname,
                        base_url=base_url,
                        api_key=api_key,
                        models=models,
                        enabled=True,
                        timeout=timeout,
                    )
                )

    return channels


def _select_channel(model: str) -> Channel:
    """Select the appropriate channel for the given model."""
    channels = _get_all_channels()

    # 1. Match specific channels that explicitly list the model
    for chan in channels:
        if chan.id != "default" and model in chan.models:
            return chan

    # 2. Fall back to the default channel
    for chan in channels:
        if chan.id == "default":
            return chan

    # 3. Fall back to any enabled channel if no default is configured
    enabled_chans = [c for c in channels if c.id != "default"]
    if enabled_chans:
        return enabled_chans[0]

    raise RuntimeError(f"No configured channels available to handle model {model!r}")


def _select_channel_by_id(channel_id: str) -> Channel:
    """Select a channel by its unique ID (for polling/queries)."""
    channels = _get_all_channels()
    for chan in channels:
        if chan.id == channel_id:
            return chan

    # Fall back to default
    for chan in channels:
        if chan.id == "default":
            return chan

    if channels:
        return channels[0]

    raise RuntimeError(f"Channel {channel_id!r} not found and no default channel available")


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Task ID Encoding & Decoding (Stateless Routing)
# ---------------------------------------------------------------------------

def _decode_id(encoded_id: str) -> tuple[str, str]:
    """Decode a stateless task ID into (channel_id, original_id)."""
    if ":" in encoded_id:
        channel_id, original_id = encoded_id.split(":", 1)
        return channel_id, original_id
    return "default", encoded_id


def _encode_response_ids(data: Any, channel_id: str) -> Any:
    """Recursively prefix task/job IDs in the response with the channel ID."""
    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            if k in ("id", "task_id") and isinstance(v, str) and v:
                if not v.startswith(f"{channel_id}:"):
                    new_data[k] = f"{channel_id}:{v}"
                else:
                    new_data[k] = v
            else:
                new_data[k] = _encode_response_ids(v, channel_id)
        return new_data
    elif isinstance(data, list):
        return [_encode_response_ids(item, channel_id) for item in data]
    return data


# ---------------------------------------------------------------------------
# Public Gateway APIs
# ---------------------------------------------------------------------------

def is_newapi_enabled() -> bool:
    """Check if the NewAPI relay is enabled and has at least one configured channel."""
    return len(_get_all_channels()) > 0


async def _query_channel_status(chan: Channel) -> dict[str, Any]:
    """Query a single channel's connection, balance, and model count."""
    result = {
        "id": chan.id,
        "name": chan.name,
        "connected": False,
        "base_url": chan.base_url,
        "balance": None,
        "quota": None,
        "username": None,
        "models_count": 0,
        "error": None,
    }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=min(chan.timeout, 10))
        ) as session:
            # 1. Try /api/user/self (standard One API / NewAPI)
            try:
                async with session.get(
                    f"{chan.base_url}/api/user/self",
                    headers=_headers(chan.api_key),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        data = body.get("data", {})
                        if isinstance(data, dict):
                            result["quota"] = data.get("quota")
                            result["username"] = data.get("username") or data.get("display_name")
                            quota = data.get("quota")
                            if quota is not None:
                                result["balance"] = round(quota / 500000, 4)
                            result["connected"] = True
            except Exception:
                pass

            # 2. Try /api/status as fallback
            if not result["connected"]:
                try:
                    async with session.get(
                        f"{chan.base_url}/api/status",
                        headers=_headers(chan.api_key),
                    ) as resp:
                        if resp.status == 200:
                            result["connected"] = True
                except Exception:
                    pass

            # 3. Fetch model list to count models
            try:
                async with session.get(
                    f"{chan.base_url}/v1/models",
                    headers=_headers(chan.api_key),
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
        result["error"] = "Unable to connect to channel"
    return result


async def get_upstream_status() -> dict[str, Any]:
    """Query status of all configured channels in parallel."""
    channels = _get_all_channels()
    if not channels:
        return {"connected": False, "error": "No channels configured"}

    tasks = [_query_channel_status(chan) for chan in channels]
    results = await asyncio.gather(*tasks)

    # Return the first/default channel status as the main dictionary,
    # and attach all channels' status under the "channels" key.
    main_result = dict(results[0])
    main_result["channels"] = results
    return main_result


async def list_models() -> list[dict[str, Any]]:
    """Fetch and merge model lists from all enabled channels."""
    channels = _get_all_channels()
    if not channels:
        return []

    async def _fetch_models(chan: Channel) -> list[dict[str, Any]]:
        url = f"{chan.base_url}/v1/models"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=min(chan.timeout, 15))
            ) as session:
                async with session.get(url, headers=_headers(chan.api_key)) as resp:
                    resp.raise_for_status()
                    body = await resp.json()
                    data = body.get("data", [])
                    if isinstance(data, list):
                        return [
                            {
                                "id": m.get("id", ""),
                                "object": "model",
                                "created": m.get("created", int(time.time())),
                                "owned_by": chan.id,
                                "name": m.get("id", ""),
                            }
                            for m in data
                            if isinstance(m, dict) and m.get("id")
                        ]
        except Exception as exc:
            logger.debug("channel {} list_models failed: error={}", chan.id, exc)
        return []

    tasks = [_fetch_models(chan) for chan in channels]
    all_lists = await asyncio.gather(*tasks)

    # Merge by model ID to avoid duplicates
    merged: dict[str, dict[str, Any]] = {}
    for model_list in all_lists:
        for m in model_list:
            mid = m["id"]
            merged[mid] = m

    return list(merged.values())


# ---------------------------------------------------------------------------
# Chat Completions
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
    """Forward a chat completion request to the matched channel."""
    chan = _select_channel(model)
    url = f"{chan.base_url}/v1/chat/completions"

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

    for key, value in kwargs.items():
        if value is not None and key not in payload:
            payload[key] = value

    logger.info(
        "newapi chat proxy: model={} stream={} url={} channel={}",
        model, stream, url, chan.id,
    )

    if stream:
        payload.setdefault("stream_options", {"include_usage": True})
        return _stream_chat(url, payload, chan.api_key, chan.timeout)
    else:
        return await _sync_chat(url, payload, chan.api_key, chan.timeout)


async def _sync_chat(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(url, json=payload, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            return await resp.json()


@dataclass
class StreamWithUsage:
    """Async SSE generator wrapper that collects usage from the final chunk."""
    _gen: Any = field(repr=False)
    usage: dict[str, Any] = field(default_factory=dict)

    def __aiter__(self):
        return self._iter()

    async def _iter(self) -> AsyncGenerator[str, None]:
        async for line in self._gen:
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
# Image Generation & Edits
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Image Generation & Edits
# ---------------------------------------------------------------------------

# In-memory mapping from video task ID to (prompt, model)
_VIDEO_TASK_METADATA: dict[str, tuple[str, str]] = {}


async def _cache_media_if_needed(url: str, media_type: str, prompt: str | None = None, model: str | None = None) -> str:
    """Download a third-party media URL and save it to the local cache, returning the local URL."""
    if not url:
        return url
    
    cfg = get_config()
    app_url = cfg.get_str("app.app_url", "").rstrip("/")
    if not app_url:
        return url  # Can't serve locally without app_url

    # Avoid caching already local URLs
    if url.startswith(app_url) or url.startswith("/v1/files/"):
        return url

    try:
        import uuid
        import urllib.parse
        from app.platform.storage import save_local_image, save_local_video
        
        file_id = str(uuid.uuid4())
        logger.info("Caching third-party {} from {}", media_type, url)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=120) as resp:
                resp.raise_for_status()
                raw = await resp.read()
                content_type = resp.headers.get("Content-Type", "")

        if media_type == "image":
            mime = content_type or "image/jpeg"
            saved_id = save_local_image(raw, mime, file_id, prompt=prompt, model=model)
            return f"{app_url}/v1/files/image?id={saved_id}"
        else:
            save_local_video(raw, file_id, prompt=prompt, model=model)
            return f"{app_url}/v1/files/video?id={file_id}"
    except Exception as e:
        logger.error("Failed to cache third-party {} from {}: {}", media_type, url, e)
        return url  # Fallback to original URL


async def _cache_image_response_if_needed(res: dict[str, Any], response_format: str, prompt: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Find image URLs in the response and cache them locally."""
    if response_format != "url" or "data" not in res:
        return res
        
    nested_data = res.get("data")
    if isinstance(nested_data, list):
        url_map = {}
        for item in nested_data:
            if isinstance(item, dict) and "url" in item:
                val = item["url"]
                if isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                    if val not in url_map:
                        url_map[val] = await _cache_media_if_needed(val, "image", prompt=prompt, model=model)
                    item["url"] = url_map[val]
    return res


async def _cache_video_response_if_needed(res: dict[str, Any], prompt: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Find video URLs in the response and cache them locally using recursive traversal."""
    status = str(res.get("status") or "").lower()
    if status not in ("success", "completed"):
        nested_data = res.get("data")
        if isinstance(nested_data, dict):
            status = str(nested_data.get("status") or "").lower()
            
    if status not in ("success", "completed"):
        return res

    url_map = {}
    
    async def get_cached_url(u: str) -> str:
        if u not in url_map:
            url_map[u] = await _cache_media_if_needed(u, "video", prompt=prompt, model=model)
        return url_map[u]

    async def traverse(node: Any) -> Any:
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
                    is_video_key = k in ("url", "video_url", "result_url")
                    is_video_ext = any(v.lower().endswith(ext) for ext in (".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"))
                    is_probable_video = is_video_key or is_video_ext or ("video" in k.lower()) or (".mp4" in v.lower())
                    if is_probable_video:
                        node[k] = await get_cached_url(v)
                else:
                    await traverse(v)
        elif isinstance(node, list):
            for item in node:
                await traverse(item)
        return node

    await traverse(res)
    return res


async def image_generations(
    *,
    model: str,
    prompt: str,
    n: int = 1,
    size: str = "1024x1024",
    response_format: str = "url",
    **kwargs: Any,
) -> dict[str, Any]:
    """Forward an image generation request to the matched channel."""
    chan = _select_channel(model)
    url = f"{chan.base_url}/v1/images/generations"

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

    logger.info("newapi image proxy: model={} url={} channel={}", model, url, chan.id)

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=chan.timeout)
    ) as session:
        async with session.post(url, json=payload, headers=_headers(chan.api_key)) as resp:
            resp.raise_for_status()
            res = await resp.json()
            return await _cache_image_response_if_needed(res, response_format, prompt=prompt, model=model)


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
    """Forward an image edit request to the matched channel."""
    chan = _select_channel(model)
    url = f"{chan.base_url}/v1/images/edits"

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "response_format": response_format,
    }
    if images_b64:
        if len(images_b64) == 1:
            payload["image"] = images_b64[0]
        else:
            payload["images"] = [{"image_url": img} for img in images_b64]

    for key, value in kwargs.items():
        if value is not None and key not in payload:
            payload[key] = value

    logger.info(
        "newapi image_edit proxy: model={} n_images={} url={} channel={}",
        model, len(images_b64 or []), url, chan.id
    )

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=chan.timeout)
    ) as session:
        async with session.post(url, json=payload, headers=_headers(chan.api_key)) as resp:
            resp.raise_for_status()
            res = await resp.json()
            return await _cache_image_response_if_needed(res, response_format, prompt=prompt, model=model)


# ---------------------------------------------------------------------------
# Video Generations & Editing
# ---------------------------------------------------------------------------

async def video_generations(
    *,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Forward a video generation request and return encoded stateless task ID."""
    model = body.get("model", "unknown")
    chan = _select_channel(model)
    url = f"{chan.base_url}/v1/video/generations"

    logger.info(
        "newapi video proxy: model={} url={} channel={}",
        model, url, chan.id,
    )

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=chan.timeout)
    ) as session:
        async with session.post(url, json=body, headers=_headers(chan.api_key)) as resp:
            resp.raise_for_status()
            res = await resp.json()
            # Store prompt/model in memory
            task_id = res.get("id") or res.get("task_id")
            if not task_id and isinstance(res.get("data"), dict):
                task_id = res.get("data").get("id") or res.get("data").get("task_id")
            if task_id:
                prompt = body.get("prompt")
                if not prompt and "messages" in body:
                    msgs = body.get("messages")
                    if msgs and isinstance(msgs, list):
                        prompt = msgs[-1].get("content")
                _VIDEO_TASK_METADATA[str(task_id)] = (prompt, model)
            return _encode_response_ids(res, chan.id)


async def video_generations_poll(task_id: str) -> dict[str, Any]:
    """Poll the status of a video generation task using the encoded channel ID."""
    channel_id, original_id = _decode_id(task_id)
    chan = _select_channel_by_id(channel_id)
    url = f"{chan.base_url}/v1/video/generations/{original_id}"

    logger.info(
        "newapi video poll proxy: task_id={} channel={} original_id={}",
        task_id, chan.id, original_id,
    )

    prompt, model = _VIDEO_TASK_METADATA.get(str(original_id), (None, None))

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=min(chan.timeout, 30))
    ) as session:
        async with session.get(url, headers=_headers(chan.api_key)) as resp:
            resp.raise_for_status()
            res = await resp.json()
            res = await _cache_video_response_if_needed(res, prompt=prompt, model=model)
            return _encode_response_ids(res, channel_id)


# ---------------------------------------------------------------------------
# Third-Party GROK Video Endpoints
# ---------------------------------------------------------------------------

THIRD_PARTY_VIDEO_MODELS: frozenset[str] = frozenset({
    "grok-imagine-video-1.5-preview",
    "grok-imagine-1.0-video",
    "grok-imagine-video-1.5-fast",
})


def is_third_party_video_model(model: str) -> bool:
    """Check if a model should use the /v1/video/create interface."""
    return model in THIRD_PARTY_VIDEO_MODELS


async def video_create(*, body: dict[str, Any]) -> dict[str, Any]:
    """Forward a video creation request via /v1/video/create and return encoded ID."""
    model = body.get("model", "unknown")
    chan = _select_channel(model)
    url = f"{chan.base_url}/v1/video/create"

    logger.info(
        "newapi video_create proxy: model={} url={} channel={}",
        model, url, chan.id,
    )

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=chan.timeout)
    ) as session:
        async with session.post(url, json=body, headers=_headers(chan.api_key)) as resp:
            resp.raise_for_status()
            res = await resp.json()
            # Store prompt/model in memory
            task_id = res.get("id") or res.get("task_id")
            if not task_id and isinstance(res.get("data"), dict):
                task_id = res.get("data").get("id") or res.get("data").get("task_id")
            if task_id:
                prompt = body.get("prompt")
                if not prompt and "messages" in body:
                    msgs = body.get("messages")
                    if msgs and isinstance(msgs, list):
                        prompt = msgs[-1].get("content")
                _VIDEO_TASK_METADATA[str(task_id)] = (prompt, model)
            return _encode_response_ids(res, chan.id)


async def video_query(video_id: str) -> dict[str, Any]:
    """Query video task status via GET /v1/video/query?id={video_id} using encoded ID."""
    channel_id, original_id = _decode_id(video_id)
    chan = _select_channel_by_id(channel_id)
    url = f"{chan.base_url}/v1/video/query"

    logger.info(
        "newapi video_query proxy: video_id={} channel={} original_id={}",
        video_id, chan.id, original_id,
    )

    prompt, model = _VIDEO_TASK_METADATA.get(str(original_id), (None, None))

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=min(chan.timeout, 30))
    ) as session:
        async with session.get(
            url,
            params={"id": original_id},
            headers=_headers(chan.api_key),
        ) as resp:
            resp.raise_for_status()
            res = await resp.json()
            res = await _cache_video_response_if_needed(res, prompt=prompt, model=model)
            return _encode_response_ids(res, channel_id)


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

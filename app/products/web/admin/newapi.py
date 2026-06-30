"""Admin NewAPI multi-channel management endpoints.

All endpoints live under ``/admin/api/newapi`` with ``verify_admin_key`` guard.
"""

from __future__ import annotations

import orjson
from fastapi import APIRouter
from fastapi.responses import Response

from app.platform.config.snapshot import get_config


router = APIRouter(prefix="/newapi", tags=["Admin - NewAPI"])


@router.get("/status")
async def newapi_status():
    """Query status of all configured channels."""
    from app.control.provider.newapi import is_newapi_enabled, get_upstream_status

    if not is_newapi_enabled():
        cfg = get_config()
        return Response(
            content=orjson.dumps({
                "enabled": False,
                "connected": False,
                "channels": [],
                "error": "NewAPI is not enabled.",
            }),
            media_type="application/json",
        )

    result = await get_upstream_status()
    result["enabled"] = True
    return Response(
        content=orjson.dumps(result),
        media_type="application/json",
    )


@router.get("/models")
async def newapi_models():
    """List all models available from all upstream channels."""
    from app.control.provider.newapi import is_newapi_enabled, list_models

    if not is_newapi_enabled():
        return Response(
            content=orjson.dumps({"items": [], "error": "NewAPI is not enabled"}),
            media_type="application/json",
        )

    models = await list_models()
    return Response(
        content=orjson.dumps({"items": models, "total": len(models)}),
        media_type="application/json",
    )


@router.get("/channels")
async def newapi_channels():
    """Return the list of configured channels (api_keys masked)."""
    cfg = get_config()
    channels_out = []

    # Default channel
    if cfg.get_bool("providers.newapi.enabled", False):
        api_key = cfg.get_str("providers.newapi.api_key", "")
        masked = (api_key[:8] + "..." + api_key[-4:]) if len(api_key) > 12 else ("*" * len(api_key))
        channels_out.append({
            "id": "default",
            "name": "Default NewAPI",
            "base_url": cfg.get_str("providers.newapi.base_url", ""),
            "api_key_masked": masked,
            "timeout": cfg.get_float("providers.newapi.timeout", 120.0),
            "models": [],
            "enabled": True,
            "is_default": True,
        })

    # Extra channels
    extra = cfg.get("providers.newapi.channels", [])
    if isinstance(extra, list):
        for item in extra:
            if not isinstance(item, dict):
                continue
            api_key = str(item.get("api_key") or "")
            masked = (api_key[:8] + "..." + api_key[-4:]) if len(api_key) > 12 else ("*" * len(api_key))
            channels_out.append({
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "base_url": str(item.get("base_url") or ""),
                "api_key_masked": masked,
                "timeout": float(item.get("timeout") or 120.0),
                "models": list(item.get("models") or []),
                "enabled": bool(item.get("enabled", True)),
                "is_default": False,
            })

    return Response(
        content=orjson.dumps({"channels": channels_out}),
        media_type="application/json",
    )


__all__ = ["router"]

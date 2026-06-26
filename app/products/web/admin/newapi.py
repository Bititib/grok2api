"""Admin NewAPI management endpoints.

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
    """Query NewAPI upstream status: connection, balance, model count."""
    from app.control.provider.newapi import is_newapi_enabled, get_upstream_status

    if not is_newapi_enabled():
        cfg = get_config()
        return Response(
            content=orjson.dumps({
                "enabled": False,
                "connected": False,
                "base_url": cfg.get_str("providers.newapi.base_url", ""),
                "error": "NewAPI is not enabled. Set providers.newapi.enabled=true in config.",
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
    """List all models available from the NewAPI upstream."""
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


@router.get("/config")
async def newapi_config():
    """Return the current NewAPI configuration (api_key masked)."""
    cfg = get_config()
    api_key = cfg.get_str("providers.newapi.api_key", "")
    masked = (api_key[:8] + "..." + api_key[-4:]) if len(api_key) > 12 else ("*" * len(api_key))

    return Response(
        content=orjson.dumps({
            "enabled": cfg.get_bool("providers.newapi.enabled", False),
            "base_url": cfg.get_str("providers.newapi.base_url", ""),
            "api_key_masked": masked,
            "timeout": cfg.get_float("providers.newapi.timeout", 120.0),
            "merge_models": cfg.get_bool("providers.newapi.merge_models", True),
            "default_input_price": cfg.get_float("providers.newapi.default_input_price", 1.0),
            "default_output_price": cfg.get_float("providers.newapi.default_output_price", 3.0),
            "default_image_price": cfg.get_float("providers.newapi.default_image_price", 0.04),
        }),
        media_type="application/json",
    )


__all__ = ["router"]

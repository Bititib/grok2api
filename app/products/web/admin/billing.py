"""Admin billing API — Key management and usage query endpoints.

All endpoints live under ``/admin/api/billing`` with ``verify_admin_key`` guard.
"""

from __future__ import annotations

from typing import Any

import orjson
from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.control.billing.service import get_billing_service, is_billing_enabled
from app.platform.errors import AppError, ErrorKind, ValidationError


router = APIRouter(prefix="/billing", tags=["Admin - Billing"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateKeyRequest(BaseModel):
    name: str = ""
    balance: float = 0.0
    group: str = "default"
    allowed_models: list[str] = Field(default_factory=list)
    expires_at: int | None = None


class UpdateKeyRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    balance: float | None = None
    group: str | None = None
    allowed_models: list[str] | None = None
    expires_at: int | None = None


class TopupRequest(BaseModel):
    amount: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_service():
    if not is_billing_enabled():
        raise AppError(
            "Billing is not enabled. Set billing.enabled=true in config.",
            kind=ErrorKind.VALIDATION,
            code="billing_disabled",
            status=400,
        )
    svc = get_billing_service()
    if svc is None:
        raise AppError(
            "Billing service not initialized",
            kind=ErrorKind.SERVER,
            code="billing_not_ready",
            status=503,
        )
    return svc


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


@router.get("/keys")
async def list_keys(
    status: str | None = Query(None),
    group: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    svc = _require_service()
    keys, total = await svc.list_keys(status=status, group=group, page=page, page_size=page_size)
    return Response(
        content=orjson.dumps({
            "items": [k.to_safe_dict() for k in keys],
            "total": total,
            "page": page,
            "page_size": page_size,
        }),
        media_type="application/json",
    )


@router.post("/keys")
async def create_key(req: CreateKeyRequest):
    svc = _require_service()
    record = await svc.create_key(
        name=req.name,
        balance=req.balance,
        group=req.group,
        allowed_models=req.allowed_models or None,
        expires_at=req.expires_at,
    )
    return Response(
        content=orjson.dumps({
            "status": "success",
            "key": record.model_dump(),
        }),
        media_type="application/json",
    )


@router.get("/keys/{key}")
async def get_key(key: str):
    svc = _require_service()
    record = await svc.repo.get_key(key)
    if record is None:
        raise ValidationError("Key not found", param="key")
    return Response(
        content=orjson.dumps(record.to_safe_dict()),
        media_type="application/json",
    )


@router.patch("/keys/{key}")
async def update_key(key: str, req: UpdateKeyRequest):
    svc = _require_service()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise ValidationError("No fields to update", param="body")
    record = await svc.update_key(key, updates)
    if record is None:
        raise ValidationError("Key not found", param="key")
    return Response(
        content=orjson.dumps({"status": "success", "key": record.to_safe_dict()}),
        media_type="application/json",
    )


@router.delete("/keys/{key}")
async def delete_key(key: str):
    svc = _require_service()
    deleted = await svc.delete_key(key)
    if not deleted:
        raise ValidationError("Key not found", param="key")
    return {"status": "success", "message": "Key deleted"}


@router.post("/keys/{key}/topup")
async def topup_key(key: str, req: TopupRequest):
    svc = _require_service()
    if req.amount <= 0:
        raise ValidationError("Amount must be positive", param="amount")
    record = await svc.topup_key(key, req.amount)
    if record is None:
        raise ValidationError("Key not found", param="key")
    return Response(
        content=orjson.dumps({
            "status": "success",
            "key": record.to_safe_dict(),
        }),
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# Usage query
# ---------------------------------------------------------------------------


@router.get("/usage")
async def query_usage(
    api_key: str | None = Query(None),
    model: str | None = Query(None),
    endpoint: str | None = Query(None),
    start_time: int | None = Query(None, description="Start time in ms"),
    end_time: int | None = Query(None, description="End time in ms"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    svc = _require_service()
    logs, total = await svc.get_usage(
        api_key=api_key,
        model=model,
        endpoint=endpoint,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return Response(
        content=orjson.dumps({
            "items": [log.model_dump() for log in logs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }),
        media_type="application/json",
    )


@router.get("/usage/summary")
async def usage_summary(
    api_key: str | None = Query(None),
    model: str | None = Query(None),
    endpoint: str | None = Query(None),
    start_time: int | None = Query(None),
    end_time: int | None = Query(None),
):
    svc = _require_service()
    summary = await svc.get_usage_summary(
        api_key=api_key,
        model=model,
        endpoint=endpoint,
        start_time=start_time,
        end_time=end_time,
    )
    return Response(
        content=orjson.dumps(summary),
        media_type="application/json",
    )


@router.get("/usage/by-model")
async def usage_by_model(
    start_time: int | None = Query(None),
    end_time: int | None = Query(None),
    source: str | None = Query(None, description="Filter: 'grok' or 'newapi'"),
):
    """Aggregate usage statistics grouped by model name.

    Optional ``source`` filter:
      - ``grok``   → only models registered in the Grok model registry
      - ``newapi`` → only models NOT in the registry (third-party)
    """
    svc = _require_service()

    conditions: list[str] = []
    params: list[Any] = []
    if start_time:
        conditions.append("created_at >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("created_at <= ?")
        params.append(end_time)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT model, endpoint,
               COUNT(*) as requests,
               COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) as completion_tokens,
               COALESCE(SUM(cost), 0) as total_cost
        FROM usage_logs{where}
        GROUP BY model, endpoint
        ORDER BY total_cost DESC
    """
    rows = await svc.repo.db.execute_fetchall(sql, params)

    # Determine source for each model
    from app.control.model import registry as model_registry

    items = []
    for r in rows:
        model_name = r[0]
        is_grok = model_registry.get(model_name) is not None
        model_source = "grok" if is_grok else "newapi"

        if source and model_source != source:
            continue

        items.append({
            "model": model_name,
            "endpoint": r[1],
            "source": model_source,
            "requests": r[2],
            "prompt_tokens": r[3],
            "completion_tokens": r[4],
            "total_cost": round(r[5], 6),
        })

    return Response(
        content=orjson.dumps({"items": items}),
        media_type="application/json",
    )


__all__ = ["router"]

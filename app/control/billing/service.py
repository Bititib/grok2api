"""Billing service — core business logic for API key auth, balance check, and usage recording.

This module is the single entry point consumed by auth middleware and endpoint
handlers.  It wraps the repository and pricing engine into a cohesive API.
"""

from __future__ import annotations

import time
from typing import Any

from app.platform.config.snapshot import get_config
from app.platform.logging.logger import logger
from .models import ApiKeyRecord, UsageLog
from .pricing import calculate_cost
from .repository import BillingRepository


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_service: BillingService | None = None


def get_billing_service() -> BillingService | None:
    return _service


def set_billing_service(svc: BillingService | None) -> None:
    global _service
    _service = svc


def is_billing_enabled() -> bool:
    """Check if billing feature is enabled in config."""
    cfg = get_config()
    return cfg.get_bool("billing.enabled", False)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BillingService:
    """High-level billing operations."""

    def __init__(self, repo: BillingRepository) -> None:
        self.repo = repo

    # ── Key lookup ────────────────────────────────────────────────────────

    async def authenticate_key(self, key: str) -> ApiKeyRecord | None:
        """Look up a key. Returns None if not found."""
        return await self.repo.get_key(key)

    # ── Balance check ─────────────────────────────────────────────────────

    async def check_balance(self, key: str) -> bool:
        record = await self.repo.get_key(key)
        if record is None:
            return False
        return record.balance > 0

    # ── Usage recording ───────────────────────────────────────────────────

    async def record_usage(
        self,
        key_record: ApiKeyRecord,
        *,
        model: str,
        endpoint: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        video_seconds: int = 0,
        request_id: str = "",
        duration_ms: int = 0,
        status: str = "success",
        error_message: str | None = None,
    ) -> float:
        """Record usage, calculate cost, deduct balance. Returns the cost."""
        cost = calculate_cost(
            model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            video_seconds=video_seconds,
            endpoint=endpoint,
        )

        # Deduct from balance
        if cost > 0:
            await self.repo.deduct_balance(key_record.key, cost)

        # Write audit log
        log = UsageLog(
            api_key=key_record.key,
            key_name=key_record.name,
            request_id=request_id,
            model=model,
            endpoint=endpoint,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            video_seconds=video_seconds,
            cost=cost,
            status=status,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        try:
            await self.repo.insert_log(log)
        except Exception as exc:
            # Don't fail the request if logging fails
            logger.warning("billing log insert failed: error={}", exc)

        logger.debug(
            "billing recorded: key={}... model={} endpoint={} cost={} balance_after={}",
            key_record.key[:8],
            model,
            endpoint,
            cost,
            key_record.balance - cost,
        )
        return cost

    # ── Admin operations ──────────────────────────────────────────────────

    async def create_key(
        self,
        *,
        name: str = "",
        balance: float = 0.0,
        group: str = "default",
        allowed_models: list[str] | None = None,
        expires_at: int | None = None,
    ) -> ApiKeyRecord:
        record = ApiKeyRecord(
            name=name,
            balance=balance,
            group=group,
            allowed_models=allowed_models or [],
            expires_at=expires_at,
        )
        await self.repo.create_key(record)
        logger.info("billing key created: key={}... name={} balance={}", record.key[:8], name, balance)
        return record

    async def list_keys(self, **kwargs) -> tuple[list[ApiKeyRecord], int]:
        return await self.repo.list_keys(**kwargs)

    async def update_key(self, key: str, updates: dict[str, Any]) -> ApiKeyRecord | None:
        return await self.repo.update_key(key, updates)

    async def delete_key(self, key: str) -> bool:
        return await self.repo.delete_key(key)

    async def topup_key(self, key: str, amount: float) -> ApiKeyRecord | None:
        result = await self.repo.topup_key(key, amount)
        if result:
            logger.info("billing key topped up: key={}... amount={} new_balance={}", key[:8], amount, result.balance)
        return result

    async def get_usage(self, **kwargs) -> tuple[list[UsageLog], int]:
        return await self.repo.query_usage(**kwargs)

    async def get_usage_summary(self, **kwargs) -> dict[str, Any]:
        return await self.repo.usage_summary(**kwargs)


__all__ = [
    "BillingService",
    "get_billing_service",
    "set_billing_service",
    "is_billing_enabled",
]

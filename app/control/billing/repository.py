"""Billing repository — independent SQLite storage for API keys and usage logs.

Uses aiosqlite for async access with a dedicated ``billing.db`` file inside
``$DATA_DIR``, completely separate from the account storage backend.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite
import orjson

from app.platform.logging.logger import logger
from app.platform.paths import data_dir
from .models import ApiKeyRecord, UsageLog


def _db_path() -> Path:
    return data_dir() / "billing.db"


_CREATE_KEYS_SQL = """
CREATE TABLE IF NOT EXISTS api_keys (
    key          TEXT PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   INTEGER NOT NULL,
    expires_at   INTEGER,
    balance      REAL NOT NULL DEFAULT 0.0,
    total_charged REAL NOT NULL DEFAULT 0.0,
    allowed_models TEXT NOT NULL DEFAULT '[]',
    "group"      TEXT NOT NULL DEFAULT 'default'
);
"""

_CREATE_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS usage_logs (
    id               TEXT PRIMARY KEY,
    api_key          TEXT NOT NULL,
    key_name         TEXT NOT NULL DEFAULT '',
    request_id       TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL DEFAULT '',
    endpoint         TEXT NOT NULL DEFAULT '',
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    video_seconds    INTEGER NOT NULL DEFAULT 0,
    cost             REAL NOT NULL DEFAULT 0.0,
    status           TEXT NOT NULL DEFAULT 'success',
    error_message    TEXT,
    created_at       INTEGER NOT NULL,
    duration_ms      INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_USAGE_IDX_SQL = """
CREATE INDEX IF NOT EXISTS idx_usage_key ON usage_logs(api_key);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_logs(model);
"""


class BillingRepository:
    """Async SQLite repository for billing data."""

    def __init__(self) -> None:
        self._db_path = _db_path()
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(_CREATE_KEYS_SQL)
        await self._db.execute(_CREATE_USAGE_SQL)
        await self._db.executescript(_CREATE_USAGE_IDX_SQL)
        await self._db.commit()
        logger.info("billing repository initialized: path={}", self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "BillingRepository not initialized"
        return self._db

    # ── API Key CRUD ──────────────────────────────────────────────────────

    async def get_key(self, key: str) -> ApiKeyRecord | None:
        async with self.db.execute("SELECT * FROM api_keys WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return self._row_to_key(row)

    async def list_keys(
        self,
        *,
        status: str | None = None,
        group: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ApiKeyRecord], int]:
        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if group:
            conditions.append('"group" = ?')
            params.append(group)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        async with self.db.execute(f"SELECT COUNT(*) FROM api_keys{where}", params) as cur:
            total = (await cur.fetchone())[0]

        offset = (page - 1) * page_size
        async with self.db.execute(
            f"SELECT * FROM api_keys{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ) as cur:
            rows = await cur.fetchall()

        return [self._row_to_key(r) for r in rows], total

    async def create_key(self, record: ApiKeyRecord) -> ApiKeyRecord:
        await self.db.execute(
            """INSERT INTO api_keys (key, name, status, created_at, expires_at,
               balance, total_charged, allowed_models, "group")
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.key,
                record.name,
                record.status,
                record.created_at,
                record.expires_at,
                record.balance,
                record.total_charged,
                orjson.dumps(record.allowed_models).decode(),
                record.group,
            ),
        )
        await self.db.commit()
        return record

    async def update_key(self, key: str, updates: dict[str, Any]) -> ApiKeyRecord | None:
        record = await self.get_key(key)
        if record is None:
            return None
        set_parts: list[str] = []
        params: list[Any] = []
        for field, value in updates.items():
            if field == "allowed_models":
                set_parts.append("allowed_models = ?")
                params.append(orjson.dumps(value).decode())
            elif field in ("name", "status", "group"):
                set_parts.append(f'"{field}" = ?')
                params.append(value)
            elif field in ("balance", "total_charged", "expires_at"):
                set_parts.append(f"{field} = ?")
                params.append(value)
        if not set_parts:
            return record
        params.append(key)
        await self.db.execute(
            f"UPDATE api_keys SET {', '.join(set_parts)} WHERE key = ?", params
        )
        await self.db.commit()
        return await self.get_key(key)

    async def delete_key(self, key: str) -> bool:
        async with self.db.execute("DELETE FROM api_keys WHERE key = ?", (key,)) as cur:
            deleted = cur.rowcount > 0
        await self.db.commit()
        return deleted

    async def topup_key(self, key: str, amount: float) -> ApiKeyRecord | None:
        await self.db.execute(
            "UPDATE api_keys SET balance = balance + ? WHERE key = ?",
            (amount, key),
        )
        await self.db.commit()
        return await self.get_key(key)

    async def deduct_balance(self, key: str, cost: float) -> bool:
        """Atomically deduct cost from key balance.

        Returns True if deduction succeeded, False if balance was insufficient.
        The WHERE clause ensures balance never goes negative.
        """
        async with self.db.execute(
            "UPDATE api_keys SET balance = balance - ?, total_charged = total_charged + ? "
            "WHERE key = ? AND balance >= ?",
            (cost, cost, key, cost),
        ) as cur:
            updated = cur.rowcount > 0
        await self.db.commit()
        return updated

    async def hold_balance(self, key: str, amount: float) -> bool:
        """Atomically hold (freeze) balance before a long-running generation.

        Deducts ``amount`` from balance upfront.  Returns True if the hold
        succeeded, False if balance was insufficient.  The caller must later
        call ``settle_hold`` to reconcile actual vs. held cost.
        """
        if amount <= 0:
            return True
        async with self.db.execute(
            "UPDATE api_keys SET balance = balance - ? "
            "WHERE key = ? AND balance >= ?",
            (amount, key, amount),
        ) as cur:
            held = cur.rowcount > 0
        await self.db.commit()
        return held

    async def settle_hold(self, key: str, held: float, actual: float) -> None:
        """Settle a previous hold: refund overpayment or charge the shortfall.

        - held > actual → refund (held - actual) to balance
        - held < actual → charge extra (actual - held) from balance
        - held == actual → only record total_charged

        ``total_charged`` is always incremented by ``actual``.
        """
        diff = held - actual  # positive = refund, negative = extra charge
        await self.db.execute(
            "UPDATE api_keys SET balance = balance + ?, "
            "total_charged = total_charged + ? WHERE key = ?",
            (diff, actual, key),
        )
        await self.db.commit()

    async def refund_hold(self, key: str, amount: float) -> None:
        """Fully refund a hold (e.g. when generation failed)."""
        if amount <= 0:
            return
        await self.db.execute(
            "UPDATE api_keys SET balance = balance + ? WHERE key = ?",
            (amount, key),
        )
        await self.db.commit()

    # ── Usage Log ─────────────────────────────────────────────────────────

    async def insert_log(self, log: UsageLog) -> None:
        await self.db.execute(
            """INSERT INTO usage_logs (id, api_key, key_name, request_id, model, endpoint,
               prompt_tokens, completion_tokens, total_tokens, video_seconds,
               cost, status, error_message, created_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log.id,
                log.api_key,
                log.key_name,
                log.request_id,
                log.model,
                log.endpoint,
                log.prompt_tokens,
                log.completion_tokens,
                log.total_tokens,
                log.video_seconds,
                log.cost,
                log.status,
                log.error_message,
                log.created_at,
                log.duration_ms,
            ),
        )
        await self.db.commit()

    async def query_usage(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[UsageLog], int]:
        conditions: list[str] = []
        params: list[Any] = []
        if api_key:
            conditions.append("api_key = ?")
            params.append(api_key)
        if model:
            conditions.append("model = ?")
            params.append(model)
        if endpoint:
            conditions.append("endpoint = ?")
            params.append(endpoint)
        if start_time:
            conditions.append("created_at >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("created_at <= ?")
            params.append(end_time)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        async with self.db.execute(f"SELECT COUNT(*) FROM usage_logs{where}", params) as cur:
            total = (await cur.fetchone())[0]

        offset = (page - 1) * page_size
        async with self.db.execute(
            f"SELECT * FROM usage_logs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ) as cur:
            rows = await cur.fetchall()

        return [self._row_to_log(r) for r in rows], total

    async def usage_summary(
        self,
        *,
        api_key: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        """Return aggregated usage statistics."""
        conditions: list[str] = []
        params: list[Any] = []
        if api_key:
            conditions.append("api_key = ?")
            params.append(api_key)
        if start_time:
            conditions.append("created_at >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("created_at <= ?")
            params.append(end_time)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        sql = f"""
            SELECT
                COUNT(*) as total_requests,
                COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(cost), 0) as total_cost,
                COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0) as success_count,
                COALESCE(SUM(CASE WHEN status='error' THEN 1 ELSE 0 END), 0) as error_count
            FROM usage_logs{where}
        """
        async with self.db.execute(sql, params) as cur:
            row = await cur.fetchone()

        return {
            "total_requests": row[0],
            "total_prompt_tokens": row[1],
            "total_completion_tokens": row[2],
            "total_tokens": row[3],
            "total_cost": round(row[4], 6),
            "success_count": row[5],
            "error_count": row[6],
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_key(row) -> ApiKeyRecord:
        d = dict(row)
        models_raw = d.get("allowed_models", "[]")
        try:
            d["allowed_models"] = orjson.loads(models_raw)
        except Exception:
            d["allowed_models"] = []
        return ApiKeyRecord(**d)

    @staticmethod
    def _row_to_log(row) -> UsageLog:
        return UsageLog(**dict(row))


__all__ = ["BillingRepository"]

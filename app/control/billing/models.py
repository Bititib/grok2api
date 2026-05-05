"""Billing data models — API key records and usage logs."""

from __future__ import annotations

import os
import time
from typing import Any

from pydantic import BaseModel, Field


def _generate_key() -> str:
    """Generate a random API key like ``sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx``."""
    return f"sk-{os.urandom(16).hex()}"


class ApiKeyRecord(BaseModel):
    """A distributable API key with balance and permissions."""

    key: str = Field(default_factory=_generate_key)
    name: str = ""
    status: str = "active"          # active | disabled | expired
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    expires_at: int | None = None   # ms timestamp, None = never

    # --- balance ---
    balance: float = 0.0            # remaining credits
    total_charged: float = 0.0      # cumulative deductions

    # --- model permissions ---
    allowed_models: list[str] = Field(default_factory=list)   # empty = all

    # --- grouping ---
    group: str = "default"

    def is_active(self) -> bool:
        if self.status != "active":
            return False
        if self.expires_at is not None and time.time() * 1000 > self.expires_at:
            return False
        return True

    def can_use_model(self, model: str) -> bool:
        if not self.allowed_models:
            return True
        return model in self.allowed_models

    def to_safe_dict(self) -> dict[str, Any]:
        """Return dict with key partially masked for display."""
        d = self.model_dump()
        if len(d["key"]) > 8:
            d["key_display"] = d["key"][:8] + "..." + d["key"][-4:]
        else:
            d["key_display"] = d["key"]
        return d


class UsageLog(BaseModel):
    """Audit record for a single API call."""

    id: str = Field(default_factory=lambda: f"log-{int(time.time()*1000)}{os.urandom(4).hex()}")
    api_key: str = ""               # full key (stored hashed or partial in DB)
    key_name: str = ""
    request_id: str = ""            # chatcmpl-xxx / resp-xxx
    model: str = ""
    endpoint: str = ""              # chat | image | video | responses

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # video-specific
    video_seconds: int = 0

    cost: float = 0.0
    status: str = "success"         # success | error
    error_message: str | None = None

    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    duration_ms: int = 0


__all__ = ["ApiKeyRecord", "UsageLog", "_generate_key"]

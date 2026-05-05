"""API-key authentication dependencies for FastAPI routes."""

import hmac

from fastapi import Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.platform.config.snapshot import get_config

_security = HTTPBearer(auto_error=False, scheme_name="API Key")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_keys() -> list[str]:
    raw = get_config("app.api_key", "")
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(k).strip() for k in raw if str(k).strip()]
    return [k.strip() for k in str(raw).split(",") if k.strip()]


def get_admin_key() -> str:
    """Return configured ``app.app_key`` (admin password)."""
    return str(get_config("app.app_key", "grok2api") or "")


def get_webui_key() -> str:
    """Return configured ``app.webui_key`` (webui access key)."""
    return str(get_config("app.webui_key", "") or "")


def is_webui_enabled() -> bool:
    """Whether the webui entry is enabled."""
    val = get_config("app.webui_enabled", False)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

async def verify_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> None:
    """Validate Bearer token against configured ``api_key`` or billing keys.

    Accepts either ``Authorization: Bearer <key>`` (OpenAI / grok2api style)
    or ``X-API-Key: <key>`` (official Anthropic SDK style) so that agents
    targeting the Anthropic-compatible endpoint work without reconfiguration.

    When billing is enabled, also checks billing API keys and stores the
    matched key record in ``request.state.billing_key``.
    """
    allowed_keys = _get_keys()
    token = _extract_bearer(authorization) or x_api_key or None

    # 1. Check global admin API keys (free pass, no billing)
    if allowed_keys and token:
        if any(hmac.compare_digest(token, k) for k in allowed_keys):
            request.state.billing_key = None
            return

    # 2. Check billing keys if billing is enabled
    from app.control.billing.service import is_billing_enabled, get_billing_service

    if is_billing_enabled():
        if token is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid Authorization header.")

        svc = get_billing_service()
        if svc is None:
            # Billing enabled but service not ready — fail closed
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing service not available.")

        key_record = await svc.authenticate_key(token)
        if key_record is not None:
            if not key_record.is_active():
                raise HTTPException(status.HTTP_403_FORBIDDEN, "API key is disabled or expired.")
            if key_record.balance <= 0:
                raise HTTPException(
                    status.HTTP_402_PAYMENT_REQUIRED,
                    "Insufficient balance. Please top up your API key.",
                )
            request.state.billing_key = key_record
            return

        # Key not found in billing DB and not in global keys
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key.")

    # 3. No billing enabled — original behaviour
    if not allowed_keys:
        request.state.billing_key = None
        return

    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid Authorization header.")

    if not any(hmac.compare_digest(token, k) for k in allowed_keys):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid API key.")

    request.state.billing_key = None


async def verify_admin_key(
    authorization: str | None = Header(default=None),
    app_key: str | None = Query(default=None),
) -> None:
    """Validate Bearer token against ``app.app_key`` (admin access).

    Accepts either ``Authorization: Bearer <key>`` header or ``?app_key=<key>``
    query parameter (the latter is needed for EventSource which cannot send headers).
    """
    key = get_admin_key()
    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin key is not configured.")

    token = _extract_bearer(authorization) or app_key
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authentication token.")

    if not hmac.compare_digest(token, key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token.")


async def verify_webui_key(
    authorization: str | None = Header(default=None),
) -> None:
    """Validate Bearer token for webui endpoints."""
    webui_key = get_webui_key()

    if not webui_key:
        if is_webui_enabled():
            return
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "WebUI access is disabled.")

    token = _extract_bearer(authorization)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authentication token.")

    if not hmac.compare_digest(token, webui_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token.")

__all__ = [
    "verify_api_key",
    "verify_admin_key",
    "verify_webui_key",
    "get_admin_key",
    "get_webui_key",
    "is_webui_enabled",
]

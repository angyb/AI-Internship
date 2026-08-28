"""API key auth, per-install/IP rate limiting, daily ask cap, and optional telemetry."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from env_utils import bool_env, int_env

logger = logging.getLogger(__name__)

_rate_lock = threading.Lock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def agent_api_key_configured() -> str:
    """Return the configured shared key, or empty string when auth is disabled."""
    return os.getenv("AGENT_API_KEY", "").strip()


def rate_limit_enabled() -> bool:
    return bool_env("AGENT_RATE_LIMIT_ENABLED", True)


def rate_limit_per_minute() -> int:
    return int_env("AGENT_RATE_LIMIT_PER_MINUTE", 20, minimum=1)


def daily_ask_limit() -> int:
    """Global asks per UTC day for POST /agent and POST /ask. 0 disables the cap."""
    return int_env("AGENT_DAILY_ASK_LIMIT", 100, minimum=0)


def override_code_configured() -> str:
    return os.getenv("AGENT_OVERRIDE_CODE", "").strip()


def telemetry_enabled() -> bool:
    return bool_env("TELEMETRY_ENABLED", False)


def _extract_presented_key(
    x_api_key: str | None,
    authorization: str | None,
) -> str:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        raw = authorization.strip()
        if raw.lower().startswith("bearer "):
            return raw[7:].strip()
        return raw
    return ""


def verify_agent_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """When AGENT_API_KEY is set, require a matching X-API-Key or Bearer token.

    When unset, auth is a no-op so local/dev and existing Streamlit remain usable.
    """
    expected = agent_api_key_configured()
    if not expected:
        return

    presented = _extract_presented_key(x_api_key, authorization)
    if not _codes_equal(presented, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Set X-API-Key (or Authorization: Bearer) to match AGENT_API_KEY.",
        )


def _client_ip(request: Request) -> str:
    """Trusted client IP: rightmost X-Forwarded-For hop (Render proxy), else peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if parts:
        return parts[-1]
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_agent_rate_limit(
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> None:
    """Sliding-window rate limit keyed by trusted client IP (not X-Install-Id)."""
    if not rate_limit_enabled():
        return
    _ = x_install_id  # accepted for compatibility; not used as a bucket key

    limit = rate_limit_per_minute()
    window = 60.0
    now = time.monotonic()
    key = f"ip:{_client_ip(request)}"

    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and (now - bucket[0]) > window:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded ({limit} requests/minute). "
                    "Wait a moment and try again."
                ),
            )
        bucket.append(now)


def _codes_equal(presented: str, expected: str) -> bool:
    """Constant-time compare via SHA-256 so unequal lengths cannot 500."""
    if not presented or not expected:
        return False
    left = hashlib.sha256(presented.encode("utf-8")).digest()
    right = hashlib.sha256(expected.encode("utf-8")).digest()
    return secrets.compare_digest(left, right)


def _utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def override_code_accepted(presented: str | None) -> bool:
    expected = override_code_configured()
    if not expected:
        return False
    return _codes_equal((presented or "").strip(), expected)


def _is_render() -> bool:
    return bool(os.getenv("RENDER_EXTERNAL_URL", "").strip())


def enforce_daily_ask_limit(
    x_override_code: Annotated[str | None, Header(alias="X-Override-Code")] = None,
) -> None:
    """Cap unauthenticated asks per UTC day. A matching AGENT_OVERRIDE_CODE skips the cap."""
    limit = daily_ask_limit()
    if limit <= 0:
        return
    if override_code_accepted(x_override_code):
        return

    import db

    if not db.database_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Daily ask limit cannot be enforced because the database is unavailable. "
                "Try again later, or enter the unlock code in the Health tab."
            ),
        )

    since = _utc_day_start()
    used = db.count_asks_since(since)
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily ask limit reached ({limit} questions per day). "
                "Enter the unlock code in the Health tab to continue, or try again tomorrow."
            ),
        )
    db.record_ask()


def require_operator_access(
    x_override_code: Annotated[str | None, Header(alias="X-Override-Code")] = None,
) -> None:
    """When AGENT_OVERRIDE_CODE is set, require a matching X-Override-Code.

    When unset locally, this is a no-op so uvicorn remains usable without a code.
    On Render, an unset code is a 503 so ingest/eval/retrieve cannot run open.
    """
    expected = override_code_configured()
    if not expected:
        if _is_render():
            raise HTTPException(
                status_code=503,
                detail="Operator code is not configured. Set AGENT_OVERRIDE_CODE on this service.",
            )
        return
    if not override_code_accepted(x_override_code):
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or missing operator code. Set X-Override-Code to match "
                "AGENT_OVERRIDE_CODE."
            ),
        )


def require_agent_access(
    _: Annotated[None, Depends(verify_agent_api_key)],
    __: Annotated[None, Depends(enforce_agent_rate_limit)],
) -> None:
    """Combined FastAPI dependency for POST /agent."""
    return None


def record_telemetry_event(
    *,
    event: str,
    message: str,
    install_id: str = "",
    extension_version: str = "",
) -> None:
    """Best-effort server log — no question text, no PII beyond install id."""
    if not telemetry_enabled():
        return
    logger.info(
        "telemetry event=%s install_id=%s version=%s message=%s",
        event[:64],
        (install_id or "-")[:64],
        (extension_version or "-")[:32],
        (message or "")[:500],
    )

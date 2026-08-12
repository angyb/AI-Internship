"""API key auth, per-install/IP rate limiting, and optional telemetry for POST /agent."""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
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
    if not presented or not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Set X-API-Key (or Authorization: Bearer) to match AGENT_API_KEY.",
        )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_agent_rate_limit(
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> None:
    """Sliding-window rate limit keyed by install ID when present, else client IP."""
    if not rate_limit_enabled():
        return

    limit = rate_limit_per_minute()
    window = 60.0
    now = time.monotonic()
    key = (x_install_id or "").strip() or f"ip:{_client_ip(request)}"

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

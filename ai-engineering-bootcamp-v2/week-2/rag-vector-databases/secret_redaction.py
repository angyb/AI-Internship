"""Redact secrets from strings and JSON payloads returned to clients."""

from __future__ import annotations

import os
import re
from typing import Any

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[a-zA-Z0-9_-]{8,}"), "sk-…"),
    (re.compile(r"pcsk_[a-zA-Z0-9_-]{8,}"), "pcsk_…"),
    (re.compile(r"rnd_[a-zA-Z0-9_-]{8,}"), "rnd_…"),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "AIza…"),
    (re.compile(r"AQ\.[0-9A-Za-z_-]{20,}"), "AQ.…"),
    (re.compile(r"Bearer\s+[^\s'\"]+"), "Bearer …"),
    (re.compile(r"(?i)([?&]key=)[^&\s'\"]+"), r"\1…"),
    (
        re.compile(
            r"(?i)\b[A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)\s*=\s*[^\s'\"]+"
        ),
        "[redacted env assignment]",
    ),
    (
        re.compile(r"postgresql(?:\+[\w]+)?://[^\s'\"]+"),
        "postgresql://[redacted]",
    ),
)

_ILLEGAL_HEADER_RE = re.compile(r"illegal header value", re.I)


def redact_secrets(text: str) -> str:
    """Remove common API keys, bearer tokens, and env assignments from text."""
    if not text:
        return text
    if _ILLEGAL_HEADER_RE.search(text):
        return (
            "Invalid API key format (contains invalid characters). "
            "Set each Environment variable on its own row."
        )
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def read_env_secret(*names: str) -> tuple[str, str | None]:
    """Return the first line of an env var; warn if extra lines were pasted in."""
    for name in names:
        raw = os.getenv(name, "")
        if not raw:
            continue
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            continue
        warning = None
        if len(lines) > 1:
            warning = (
                f"{name} contains multiple lines — set each variable on its own row "
                "in Render Environment."
            )
        return lines[0], warning
    return "", None


def safe_error_message(exc: BaseException, *, prefix: str = "") -> str:
    """Format an exception for API/UI responses without leaking secrets."""
    message = redact_secrets(str(exc))
    if prefix:
        return f"{prefix}: {message}"[:400]
    return message[:400]


def sanitize_for_client(value: Any) -> Any:
    """Recursively redact secrets from JSON-serializable health/API payloads."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: sanitize_for_client(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_for_client(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_client(item) for item in value]
    return value

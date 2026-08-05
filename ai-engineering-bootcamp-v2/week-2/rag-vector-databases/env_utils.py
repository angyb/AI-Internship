"""Shared environment-variable parsing helpers.

Centralizes bool/int/float parsing so every config module uses the same
conventions. An unset or blank variable always falls back to the default.
"""

from __future__ import annotations

import os

_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


def bool_env(name: str, default: bool) -> bool:
    """Parse a boolean env var. Unset/blank/unrecognized values return the default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def int_env(name: str, default: int, *, minimum: int = 1) -> int:
    """Parse an int env var, clamped to ``minimum``. Bad values return the default."""
    raw = os.getenv(name, str(default)).strip()
    try:
        return max(int(raw), minimum)
    except ValueError:
        return default


def float_env(name: str, default: float, *, minimum: float | None = None) -> float:
    """Parse a float env var. Bad values return the default; optionally clamped to ``minimum``."""
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None:
        return max(value, minimum)
    return value

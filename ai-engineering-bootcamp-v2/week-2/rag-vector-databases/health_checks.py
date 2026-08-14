"""Dependency checks for GET /health — used by the Ask Z-Bot Health tab."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from env_utils import bool_env

_PINECONE_CACHE_TTL_S = 20.0
_pinecone_cache: tuple[float, dict[str, Any]] | None = None


def _check(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail}


def pinecone_error_detail(exc: BaseException) -> str:
    """Turn a Pinecone SDK/HTTP error into a short Health-tab message."""
    text = str(exc)
    lower = text.lower()
    if "egress limit" in lower:
        return (
            "Monthly egress limit reached. Vector search is unavailable until "
            "the quota resets or the Pinecone plan is upgraded."
        )
    if "429" in text or "rate limit" in lower:
        return "Rate limited: " + text[:280]
    return text[:400]


def _check_pinecone_uncached() -> dict[str, Any]:
    try:
        from ingest import _pinecone_index

        stats = _pinecone_index().describe_index_stats()
        count = int(getattr(stats, "total_vector_count", 0) or 0)
        dimension = int(getattr(stats, "dimension", 0) or 0)
        if count <= 0:
            result = _check(False, "Index is empty — ingest documents before asking.")
            result["vector_count"] = count
            result["dimension"] = dimension
            return result
        result = _check(True, f"{count:,} vectors in index")
        result["vector_count"] = count
        result["dimension"] = dimension
        return result
    except KeyError as exc:
        return _check(False, f"Missing environment variable: {exc.args[0]}")
    except Exception as exc:
        return _check(False, pinecone_error_detail(exc))


def check_pinecone() -> dict[str, Any]:
    global _pinecone_cache
    now = time.monotonic()
    if _pinecone_cache and now - _pinecone_cache[0] < _PINECONE_CACHE_TTL_S:
        return _pinecone_cache[1]
    result = _check_pinecone_uncached()
    _pinecone_cache = (now, result)
    return result


def check_embeddings() -> dict[str, Any]:
    if os.getenv("OPENAI_API_KEY", "").strip():
        return _check(True, "OPENAI_API_KEY set")
    return _check(False, "OPENAI_API_KEY is not set — query embeddings will fail.")


def check_gemini() -> dict[str, Any]:
    if os.getenv("GOOGLE_API_KEY", "").strip():
        return _check(True, "GOOGLE_API_KEY set")
    return _check(False, "GOOGLE_API_KEY is not set — the agent cannot run.")


def check_bm25() -> dict[str, Any]:
    if not bool_env("HYBRID_SEARCH", True):
        return _check(True, "Hybrid search disabled")
    try:
        from bm25_index import get_bm25_index

        count = get_bm25_index().record_count()
        if count <= 0:
            return _check(
                False,
                "Keyword index is empty — hybrid search will miss until Postgres load or ingest.",
            )
        return _check(True, f"{count:,} chunks indexed")
    except Exception as exc:
        return _check(False, str(exc)[:400])


def check_database() -> dict[str, Any]:
    import db

    if not db.database_enabled():
        return _check(False, "DATABASE_URL is not set — History will be unavailable.")
    try:
        db.ping()
        return _check(True, "Connected")
    except Exception as exc:
        return _check(False, str(exc)[:400])


_CHECKS: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
    ("pinecone", check_pinecone),
    ("embeddings", check_embeddings),
    ("gemini", check_gemini),
    ("bm25", check_bm25),
    ("database", check_database),
)


def collect_health() -> dict[str, Any]:
    """Return API liveness plus per-dependency checks. Always safe to serialize."""
    from usage_checks import collect_usage, usage_level

    checks: dict[str, Any] = {}
    all_ok = True
    for name, fn in _CHECKS:
        result = fn()
        checks[name] = result
        if not result.get("ok"):
            all_ok = False
    usage = collect_usage()
    level = usage_level(usage)
    status = "ok" if all_ok else "degraded"
    if all_ok and level == "over":
        status = "degraded"
    return {
        "status": status,
        "usage_level": level,
        "checks": checks,
        "usage": usage,
    }

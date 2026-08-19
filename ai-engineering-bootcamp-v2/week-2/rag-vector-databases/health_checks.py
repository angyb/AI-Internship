"""Dependency checks for GET /health — used by the Ask Z-Bot Health tab."""

from __future__ import annotations

import os
import time
from typing import Any, Callable
from urllib.parse import quote

from env_utils import bool_env
from secret_redaction import redact_secrets, safe_error_message, sanitize_for_client

_PINECONE_CACHE_TTL_S = 20.0
_pinecone_cache: tuple[float, dict[str, Any]] | None = None

_GEMINI_CACHE_TTL_S = 60.0
_GEMINI_HTTP_TIMEOUT_S = 10.0
_gemini_cache: tuple[float, dict[str, Any]] | None = None


def _check(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail}


def pinecone_error_detail(exc: BaseException) -> str:
    """Turn a Pinecone SDK/HTTP error into a short Health-tab message."""
    text = redact_secrets(str(exc))
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


def _gemini_agent_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip() or "gemini-flash-latest"


def _gemini_api_error_message(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return redact_secrets(str(err.get("message") or err))[:280]
        if isinstance(err, str) and err:
            return redact_secrets(err)[:280]
        if body.get("message"):
            return redact_secrets(str(body["message"]))[:280]
    if isinstance(body, str) and body:
        return redact_secrets(body)[:280]
    return "request failed"


def _gemini_smoke_error_detail(status: int, body: Any) -> str:
    msg = _gemini_api_error_message(body)
    if status == 403:
        return (
            f"Agent cannot run ({msg}). Update GOOGLE_API_KEY on Render and confirm "
            "Generative Language API access in Google AI Studio."
        )
    return f"Gemini generateContent failed ({status}): {msg}"


def _gemini_generate_smoke(key: str, model: str) -> tuple[int, Any]:
    """Minimal generateContent call using the same model as POST /agent."""
    import httpx

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model)}:generateContent?key={quote(key)}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Reply with exactly: ok"}]}],
        "generationConfig": {"maxOutputTokens": 8, "temperature": 0},
    }
    with httpx.Client(timeout=_GEMINI_HTTP_TIMEOUT_S) as client:
        resp = client.post(url, json=payload)
        try:
            body = resp.json()
        except Exception:
            body = {"error": redact_secrets((resp.text or "")[:300])}
        return resp.status_code, body


def _check_gemini_uncached() -> dict[str, Any]:
    key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not key:
        return _check(False, "GOOGLE_API_KEY is not set — the agent cannot run.")

    model = _gemini_agent_model()
    try:
        status, body = _gemini_generate_smoke(key, model)
    except Exception as exc:
        return _check(False, safe_error_message(exc))

    if status != 200:
        return _check(False, _gemini_smoke_error_detail(status, body))

    candidates = body.get("candidates") if isinstance(body, dict) else None
    if not candidates:
        return _check(
            False,
            f"Gemini returned no candidates for model {model} — POST /agent may fail.",
        )
    return _check(
        True,
        f"Agent model {model} responded — POST /agent should work.",
    )


def check_gemini() -> dict[str, Any]:
    global _gemini_cache
    now = time.monotonic()
    if _gemini_cache and now - _gemini_cache[0] < _GEMINI_CACHE_TTL_S:
        return _gemini_cache[1]
    result = _check_gemini_uncached()
    _gemini_cache = (now, result)
    return result


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
        return _check(False, safe_error_message(exc))


def check_database() -> dict[str, Any]:
    import db

    if not db.database_enabled():
        return _check(False, "DATABASE_URL is not set — History will be unavailable.")
    try:
        db.ping()
        return _check(True, "Connected")
    except Exception as exc:
        return _check(False, safe_error_message(exc))


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
    return sanitize_for_client(
        {
            "status": status,
            "usage_level": level,
            "checks": checks,
            "usage": usage,
        }
    )

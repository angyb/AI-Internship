"""Vendor usage / quota snapshots for GET /health — Ask Z-Bot Usage section.

Remaining prepaid credits are not exposed by most of these APIs. We report what
each vendor actually returns, plus plan-based remaining GB when a limit is known.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from env_utils import float_env
from secret_redaction import read_env_secret, redact_secrets, safe_error_message

def _usage_cache_ttl_s() -> float:
    return float_env("USAGE_CACHE_TTL_S", 300.0, minimum=30.0)
_HTTP_TIMEOUT_S = 8.0
_usage_cache: tuple[float, dict[str, Any]] | None = None

DASHBOARDS = {
    "openai": "https://platform.openai.com/usage",
    "pinecone": "https://app.pinecone.io/organizations/-/settings/usage",
    "gemini": "https://aistudio.google.com/usage",
    "render": "https://dashboard.render.com/billing",
}

# Pinecone Starter / Builder storage + egress allowances (serverless).
# Standard/Enterprise storage is unlimited; egress is billed past the allowance.
_PINECONE_PLANS: dict[str, dict[str, float | None]] = {
    "starter": {"storage_gb": 2.0, "egress_gb": 1.0},
    "free": {"storage_gb": 2.0, "egress_gb": 1.0},
    "builder": {"storage_gb": 10.0, "egress_gb": 10.0},
    "standard": {"storage_gb": None, "egress_gb": 100.0},
    "enterprise": {"storage_gb": None, "egress_gb": 100.0},
}

# Hobby workspace included outbound bandwidth after April 2026 plans.
_DEFAULT_RENDER_BANDWIDTH_GB = 5.0

# Gemini 2.5 Flash paid-tier list prices (USD per 1M tokens, Aug 2026).
_GEMINI_INPUT_USD_PER_M = 0.30
_GEMINI_OUTPUT_USD_PER_M = 2.50
# Gemini API Tier 1 billing-account spend cap when GEMINI_MONTHLY_BUDGET_USD is unset.
_DEFAULT_GEMINI_BUDGET_USD = 250.0

_LEVEL_RANK = {"ok": 0, "info": 0, "warn": 1, "over": 2}


def _item(
    *,
    ok: bool,
    level: str,
    detail: str,
    meters: list[dict[str, Any]] | None = None,
    dashboard: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "level": level,
        "detail": detail,
        "meters": meters or [],
        "dashboard": dashboard,
    }


def _meter(
    label: str,
    used: float,
    limit: float | None,
    unit: str,
) -> dict[str, Any]:
    pct = None
    if limit is not None and limit > 0:
        pct = round(100.0 * used / limit, 1)
    return {
        "label": label,
        "used": used,
        "limit": limit,
        "unit": unit,
        "pct": pct,
    }


def _level_from_pct(pct: float | None) -> str:
    if pct is None:
        return "info"
    if pct >= 100:
        return "over"
    if pct >= 80:
        return "warn"
    return "ok"


def _worst_level(levels: list[str]) -> str:
    worst = "ok"
    for level in levels:
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(worst, 0):
            worst = level
    return worst


def usage_level(usage: dict[str, Any]) -> str:
    """Aggregate warn/over across vendor snapshots. Missing vendors are ok."""
    return _worst_level(
        [str(item.get("level") or "ok") for item in usage.values() if isinstance(item, dict)]
    )


def _http_get(url: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    import httpx

    safe_headers = headers or {}
    for name, value in safe_headers.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"{name} contains invalid characters")

    with httpx.Client(timeout=_HTTP_TIMEOUT_S) as client:
        resp = client.get(url, headers=safe_headers)
        try:
            data = resp.json()
        except Exception:
            text = redact_secrets((resp.text or "")[:300])
            data = {"error": text} if text else None
        return resp.status_code, data


def _error_message(body: Any) -> str:
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


def _month_start_utc() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _period_label(start: datetime) -> str:
    return start.strftime("%Y-%m")


def _to_gb(value: float, unit: str) -> float:
    """Convert a Render metrics value to decimal GB (1000 MB = 1 GB)."""
    u = (unit or "mb").strip().lower()
    if u in {"bytes", "b"}:
        return value / 1_000_000_000
    if u in {"kb", "kib"}:
        return value / 1_000_000
    if u in {"mb", "mib"}:
        return value / 1_000
    if u in {"gb", "gib"}:
        return value
    return value / 1_000


def _series_total(payload: Any, *, gauge: bool = False) -> tuple[float, str]:
    """Sum counter series, or take the latest point for a gauge."""
    total = 0.0
    unit = "mb"
    rows = payload if isinstance(payload, list) else []
    for series in rows:
        if not isinstance(series, dict):
            continue
        unit = str(series.get("unit") or unit)
        values = series.get("values") or []
        if not isinstance(values, list) or not values:
            continue
        if gauge:
            last = values[-1]
            if isinstance(last, dict):
                total += float(last.get("value") or 0)
        else:
            for point in values:
                if isinstance(point, dict):
                    total += float(point.get("value") or 0)
    return total, unit


def _format_qty(value: float, unit: str, digits: int = 2) -> str:
    if unit.upper() == "USD":
        return f"${value:,.{digits}f}"
    if abs(value) >= 100:
        return f"{value:,.0f} {unit}"
    if abs(value) >= 10:
        return f"{value:,.1f} {unit}"
    return f"{value:,.{digits}f} {unit}"


def _format_of(used: float, limit: float | None, unit: str) -> str:
    if limit is None:
        return _format_qty(used, unit)
    return f"{_format_qty(used, unit)} of {_format_qty(limit, unit)}"


def pinecone_storage_gb(vector_count: int, dimension: int) -> float:
    """Rough serverless storage from dense float32 vectors + a metadata pad."""
    if vector_count <= 0 or dimension <= 0:
        return 0.0
    bytes_per_vector = dimension * 4 + 256
    return (vector_count * bytes_per_vector) / 1_000_000_000


def usage_openai() -> dict[str, Any]:
    admin_key, admin_warn = read_env_secret("OPENAI_ADMIN_KEY")
    api_key, api_warn = read_env_secret("OPENAI_API_KEY")
    key = admin_key or api_key
    env_warn = admin_warn or api_warn
    dashboard = DASHBOARDS["openai"]
    if env_warn:
        return _item(
            ok=True,
            level="info",
            detail=env_warn,
            dashboard=dashboard,
        )
    if not key:
        return _item(
            ok=False,
            level="info",
            detail="OPENAI_API_KEY is not set.",
            dashboard=dashboard,
        )

    start = _month_start_utc()
    start_unix = int(start.timestamp())
    period = _period_label(start)
    headers = {"Authorization": f"Bearer {key}"}
    status, body = _http_get(
        "https://api.openai.com/v1/organization/costs"
        f"?start_time={start_unix}&bucket_width=1d&limit=31",
        headers,
    )
    if status == 403:
        return _item(
            ok=True,
            level="info",
            detail=(
                f"Spend for {period} needs an OpenAI Admin key with api.usage.read "
                "(set OPENAI_ADMIN_KEY). Remaining prepaid credits are not available "
                "via API — see the Usage dashboard."
            ),
            dashboard=dashboard,
        )
    if status != 200:
        return _item(
            ok=True,
            level="info",
            detail=f"OpenAI usage API: {_error_message(body)}",
            dashboard=dashboard,
        )

    spent = 0.0
    currency = "usd"
    buckets = (body or {}).get("data") if isinstance(body, dict) else None
    for bucket in buckets or []:
        if not isinstance(bucket, dict):
            continue
        for row in bucket.get("results") or []:
            if not isinstance(row, dict):
                continue
            amount = row.get("amount") or {}
            if isinstance(amount, dict):
                spent += float(amount.get("value") or 0)
                currency = str(amount.get("currency") or currency)

    budget = float_env("OPENAI_MONTHLY_BUDGET_USD", 0.0, minimum=0.0)
    limit = budget if budget > 0 else None
    unit = currency.upper() if currency else "USD"
    meter = _meter(f"Spend ({period})", spent, limit, unit)
    level = _level_from_pct(meter["pct"]) if limit is not None else "info"
    if limit is None:
        detail = (
            f"{_format_qty(spent, unit)} spent in {period}. Remaining prepaid "
            "credits are not available via API."
        )
    else:
        detail = f"{_format_of(spent, limit, unit)} budget used in {period}."
    return _item(
        ok=level != "over",
        level=level,
        detail=detail,
        meters=[meter],
        dashboard=dashboard,
    )


def usage_pinecone() -> dict[str, Any]:
    from health_checks import check_pinecone, pinecone_error_detail

    dashboard = DASHBOARDS["pinecone"]
    check = check_pinecone()
    if not check.get("ok"):
        return _item(
            ok=False,
            level="over" if "egress" in str(check.get("detail") or "").lower() else "info",
            detail=str(check.get("detail") or pinecone_error_detail(RuntimeError("Pinecone unavailable"))),
            dashboard=dashboard,
        )

    count = int(check.get("vector_count") or 0)
    dimension = int(check.get("dimension") or 0)
    stored_gb = pinecone_storage_gb(count, dimension)
    plan_name = (os.getenv("PINECONE_PLAN", "starter") or "starter").strip().lower()
    plan = _PINECONE_PLANS.get(plan_name) or _PINECONE_PLANS["starter"]
    storage_limit = plan.get("storage_gb")
    egress_limit = plan.get("egress_gb")

    meters = [_meter("Estimated storage", stored_gb, storage_limit, "GB")]
    storage_level = _level_from_pct(meters[0]["pct"]) if storage_limit else "ok"
    storage_txt = _format_of(stored_gb, storage_limit, "GB") if stored_gb or storage_limit else "n/a"
    egress_txt = (
        f"{egress_limit:g} GB/mo egress included"
        if egress_limit is not None
        else "egress billed past the plan allowance"
    )
    detail = (
        f"{count:,} vectors · ~{storage_txt} storage ({plan_name} plan). "
        f"Remaining monthly egress is not exposed via API ({egress_txt}); "
        "Health will flag it when the quota is exhausted."
    )
    return _item(
        ok=True,
        level=storage_level,
        detail=detail,
        meters=meters,
        dashboard=dashboard,
    )


def estimate_gemini_usd(prompt_tokens: int, total_tokens: int) -> float:
    """Estimate paid-tier Flash cost from prompt + total token counts."""
    prompt = max(int(prompt_tokens or 0), 0)
    total = max(int(total_tokens or 0), prompt)
    output = total - prompt
    if prompt == 0 and total > 0:
        prompt = int(total * 0.8)
        output = total - prompt
    return (prompt / 1_000_000.0) * _GEMINI_INPUT_USD_PER_M + (
        output / 1_000_000.0
    ) * _GEMINI_OUTPUT_USD_PER_M


def _gemini_month_tokens() -> dict[str, int]:
    import db

    if not db.database_enabled():
        return {"prompt_tokens": 0, "total_tokens": 0, "turns": 0}
    try:
        return db.sum_assistant_tokens_since(_month_start_utc())
    except Exception:
        return {"prompt_tokens": 0, "total_tokens": 0, "turns": 0}


def usage_gemini() -> dict[str, Any]:
    key, env_warn = read_env_secret("GOOGLE_API_KEY", "GEMINI_API_KEY")
    dashboard = DASHBOARDS["gemini"]
    if env_warn:
        return _item(
            ok=True,
            level="info",
            detail=env_warn,
            dashboard=dashboard,
        )
    if not key:
        return _item(
            ok=False,
            level="info",
            detail="GOOGLE_API_KEY is not set.",
            dashboard=dashboard,
        )
    status, body = _http_get(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={quote(key)}&pageSize=1"
    )
    if status != 200:
        return _item(
            ok=False,
            level="info",
            detail=f"Gemini API: {_error_message(body)}",
            dashboard=dashboard,
        )

    start = _month_start_utc()
    period = _period_label(start)
    tokens = _gemini_month_tokens()
    spent = estimate_gemini_usd(
        int(tokens.get("prompt_tokens") or 0),
        int(tokens.get("total_tokens") or 0),
    )
    budget = float_env(
        "GEMINI_MONTHLY_BUDGET_USD",
        _DEFAULT_GEMINI_BUDGET_USD,
        minimum=0.0,
    )
    limit = budget if budget > 0 else None
    meter = _meter(f"Est. spend ({period})", spent, limit, "USD")
    level = _level_from_pct(meter["pct"]) if limit is not None else "info"
    turns = int(tokens.get("turns") or 0)
    turn_txt = f"{turns:,} Ask Z-Bot turn" + ("s" if turns != 1 else "")
    if limit is None:
        detail = (
            f"~{_format_qty(spent, 'USD')} estimated Flash cost this month "
            f"({turn_txt}). Google does not expose billed spend via API key."
        )
    else:
        cap_note = (
            "Tier 1 $250 cap"
            if abs(limit - _DEFAULT_GEMINI_BUDGET_USD) < 1e-9
            and not os.getenv("GEMINI_MONTHLY_BUDGET_USD", "").strip()
            else "budget"
        )
        detail = (
            f"{_format_of(spent, limit, 'USD')} {cap_note} used in {period} "
            f"({turn_txt}, Flash list prices). Billed project spend is only on "
            "the Gemini Usage dashboard."
        )
    return _item(
        ok=level != "over",
        level=level,
        detail=detail,
        meters=[meter],
        dashboard=dashboard,
    )


def usage_render() -> dict[str, Any]:
    api_key, env_warn = read_env_secret("RENDER_API_KEY")
    dashboard = DASHBOARDS["render"]
    if env_warn:
        return _item(
            ok=True,
            level="info",
            detail=env_warn,
            dashboard=dashboard,
        )
    if not api_key:
        return _item(
            ok=True,
            level="info",
            detail=(
                "Set RENDER_API_KEY on this API to show workspace bandwidth and "
                "Postgres disk. Remaining account credits are not in the Render API."
            ),
            dashboard=dashboard,
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    start = _month_start_utc()
    start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    period = _period_label(start)
    included_gb = float_env(
        "RENDER_INCLUDED_BANDWIDTH_GB",
        _DEFAULT_RENDER_BANDWIDTH_GB,
        minimum=0.0,
    )
    bandwidth_limit = included_gb if included_gb > 0 else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        svc_fut = pool.submit(
            _http_get, "https://api.render.com/v1/services?limit=100", headers
        )
        pg_fut = pool.submit(
            _http_get, "https://api.render.com/v1/postgres?limit=100", headers
        )
        status, body = svc_fut.result()
        pg_status, pg_body = pg_fut.result()
    if status != 200:
        return _item(
            ok=True,
            level="info",
            detail=f"Render API: {_error_message(body)}",
            dashboard=dashboard,
        )

    services: list[dict[str, Any]] = []
    rows = body if isinstance(body, list) else []
    for row in rows:
        service = row.get("service") if isinstance(row, dict) and "service" in row else row
        if isinstance(service, dict) and service.get("id"):
            services.append(service)

    metric_jobs: list[tuple[str, str, bool]] = []
    plans: list[str] = []
    for service in services:
        sid = str(service["id"])
        details = service.get("serviceDetails") or {}
        plan = str((details.get("plan") if isinstance(details, dict) else None) or "unknown")
        name = str(service.get("name") or sid)
        plans.append(f"{name} ({plan})")
        metric_jobs.append(
            (
                "bw",
                "https://api.render.com/v1/metrics/bandwidth"
                f"?resource={quote(sid)}"
                f"&startTime={quote(start_iso)}&endTime={quote(end_iso)}",
                False,
            )
        )

    disk_limit = None
    if pg_status == 200 and isinstance(pg_body, list):
        for row in pg_body:
            postgres = row.get("postgres") if isinstance(row, dict) and "postgres" in row else row
            if not isinstance(postgres, dict) or not postgres.get("id"):
                continue
            raw_limit = postgres.get("diskSizeGB")
            if raw_limit is not None:
                disk_limit = (disk_limit or 0.0) + float(raw_limit)
            metric_jobs.append(
                (
                    "disk",
                    "https://api.render.com/v1/metrics/disk-usage"
                    f"?resource={quote(str(postgres['id']))}"
                    f"&startTime={quote(start_iso)}&endTime={quote(end_iso)}",
                    True,
                )
            )

    bandwidth_gb = 0.0
    disk_gb = 0.0
    if metric_jobs:
        with ThreadPoolExecutor(max_workers=min(6, len(metric_jobs))) as pool:
            futures = [
                (kind, gauge, pool.submit(_http_get, url, headers))
                for kind, url, gauge in metric_jobs
            ]
            for kind, gauge, fut in futures:
                code, payload = fut.result()
                if code != 200:
                    continue
                total, unit = _series_total(payload, gauge=gauge)
                gb = _to_gb(total, unit)
                if kind == "bw":
                    bandwidth_gb += gb
                else:
                    disk_gb += gb

    meters = [
        _meter(f"Outbound bandwidth ({period})", bandwidth_gb, bandwidth_limit, "GB"),
    ]
    if disk_limit is not None or disk_gb > 0:
        meters.append(_meter("Postgres disk", disk_gb, disk_limit, "GB"))

    levels = [_level_from_pct(m.get("pct")) for m in meters]
    level = _worst_level(levels)
    plan_txt = ", ".join(plans) if plans else "no services"
    detail = (
        f"{_format_of(bandwidth_gb, bandwidth_limit, 'GB')} outbound this month. "
        f"Services: {plan_txt}. Remaining workspace credits are not in the Render API."
    )
    return _item(
        ok=level != "over",
        level=level,
        detail=detail,
        meters=meters,
        dashboard=dashboard,
    )


_COLLECTORS: tuple[tuple[str, Any], ...] = (
    ("render", usage_render),
    ("pinecone", usage_pinecone),
    ("openai", usage_openai),
    ("gemini", usage_gemini),
)


def collect_usage(*, force: bool = False) -> dict[str, Any]:
    """Fetch vendor usage in parallel. Cached briefly; never raises."""
    global _usage_cache
    now = time.monotonic()
    ttl = _usage_cache_ttl_s()
    if not force and _usage_cache and now - _usage_cache[0] < ttl:
        return _usage_cache[1]

    usage: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(fn) for name, fn in _COLLECTORS}
        for name, future in futures.items():
            try:
                usage[name] = future.result(timeout=_HTTP_TIMEOUT_S + 4)
            except Exception as exc:
                usage[name] = _item(
                    ok=True,
                    level="info",
                    detail=safe_error_message(exc, prefix="Could not fetch usage")[:280],
                    dashboard=DASHBOARDS.get(name, ""),
                )
    _usage_cache = (now, usage)
    return usage

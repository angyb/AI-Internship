"""Unit tests for usage_checks — mocked HTTP, no live vendor calls."""

from __future__ import annotations

from usage_checks import (
    _format_of,
    _level_from_pct,
    _series_total,
    _to_gb,
    estimate_gemini_usd,
    pinecone_storage_gb,
    usage_gemini,
    usage_level,
    usage_openai,
    usage_pinecone,
    usage_render,
)


def test_to_gb_decimal() -> None:
    assert abs(_to_gb(110.524, "mb") - 0.110524) < 1e-9
    assert abs(_to_gb(5_000_000_000, "bytes") - 5.0) < 1e-9
    assert _to_gb(2.5, "gb") == 2.5


def test_series_total_sums_counters_and_gauges() -> None:
    payload = [
        {
            "unit": "mb",
            "values": [{"value": 10.0}, {"value": 2.5}],
        }
    ]
    total, unit = _series_total(payload, gauge=False)
    assert unit == "mb"
    assert total == 12.5
    gauge, _ = _series_total(payload, gauge=True)
    assert gauge == 2.5


def test_pinecone_storage_estimate() -> None:
    gb = pinecone_storage_gb(15776, 1536)
    assert 0.09 < gb < 0.12


def test_level_from_pct() -> None:
    assert _level_from_pct(None) == "info"
    assert _level_from_pct(12.0) == "ok"
    assert _level_from_pct(80.0) == "warn"
    assert _level_from_pct(100.0) == "over"


def test_format_of_usd() -> None:
    assert _format_of(1.234, 10.0, "USD") == "$1.23 of $10.00"


def test_openai_missing_admin_scope(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)

    def fake_get(url, headers=None):
        return 403, {"error": {"message": "Missing scopes: api.usage.read"}}

    monkeypatch.setattr("usage_checks._http_get", fake_get)
    result = usage_openai()
    assert result["ok"] is True
    assert result["level"] == "info"
    assert "OPENAI_ADMIN_KEY" in result["detail"]
    assert result["meters"] == []


def test_openai_spend_against_budget(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "sk-admin-test")
    monkeypatch.setenv("OPENAI_MONTHLY_BUDGET_USD", "10")

    def fake_get(url, headers=None):
        return 200, {
            "data": [
                {
                    "results": [
                        {"amount": {"value": 3.5, "currency": "usd"}},
                        {"amount": {"value": 1.0, "currency": "usd"}},
                    ]
                }
            ]
        }

    monkeypatch.setattr("usage_checks._http_get", fake_get)
    result = usage_openai()
    assert result["level"] == "ok"
    assert result["meters"][0]["used"] == 4.5
    assert result["meters"][0]["limit"] == 10.0
    assert result["meters"][0]["pct"] == 45.0


def test_pinecone_usage_from_health_check(monkeypatch) -> None:
    monkeypatch.setenv("PINECONE_PLAN", "starter")

    def fake_check():
        return {
            "ok": True,
            "detail": "15,776 vectors in index",
            "vector_count": 15776,
            "dimension": 1536,
        }

    monkeypatch.setattr("health_checks.check_pinecone", fake_check)
    result = usage_pinecone()
    assert result["ok"] is True
    assert result["meters"][0]["limit"] == 2.0
    assert result["meters"][0]["pct"] < 10
    assert "egress" in result["detail"].lower()


def test_estimate_gemini_usd() -> None:
    # 1M input + 200k output at Flash rates: $0.30 + $0.50 = $0.80
    assert abs(estimate_gemini_usd(1_000_000, 1_200_000) - 0.80) < 1e-9


def test_gemini_key_valid_no_remaining(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MONTHLY_BUDGET_USD", raising=False)

    def fake_get(url, headers=None):
        return 200, {"models": [{"name": "models/gemini-2.5-flash"}]}

    monkeypatch.setattr("usage_checks._http_get", fake_get)
    monkeypatch.setattr(
        "usage_checks._gemini_month_tokens",
        lambda: {"prompt_tokens": 0, "total_tokens": 0, "turns": 0},
    )
    result = usage_gemini()
    assert result["ok"] is True
    assert result["meters"][0]["used"] == 0.0
    assert result["meters"][0]["limit"] == 250.0
    assert "tier 1" in result["detail"].lower()


def test_gemini_budget_from_tokens(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MONTHLY_BUDGET_USD", "10")

    def fake_get(url, headers=None):
        return 200, {"models": [{"name": "models/gemini-2.5-flash"}]}

    monkeypatch.setattr("usage_checks._http_get", fake_get)
    monkeypatch.setattr(
        "usage_checks._gemini_month_tokens",
        lambda: {"prompt_tokens": 1_000_000, "total_tokens": 1_200_000, "turns": 12},
    )
    result = usage_gemini()
    assert result["ok"] is True
    assert result["level"] == "ok"
    assert result["meters"][0]["used"] == 0.8
    assert result["meters"][0]["limit"] == 10.0
    assert result["meters"][0]["pct"] == 8.0
    assert "12" in result["detail"]


def test_render_bandwidth_and_disk(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "rnd_test")
    monkeypatch.setenv("RENDER_INCLUDED_BANDWIDTH_GB", "5")

    def fake_get(url, headers=None):
        if url.startswith("https://api.render.com/v1/services?"):
            return 200, [
                {
                    "service": {
                        "id": "srv-1",
                        "name": "week-2-rag-api",
                        "serviceDetails": {"plan": "standard"},
                    }
                }
            ]
        if "metrics/bandwidth" in url:
            return 200, [{"unit": "mb", "values": [{"value": 500.0}, {"value": 500.0}]}]
        if url.startswith("https://api.render.com/v1/postgres"):
            return 200, [{"postgres": {"id": "dpg-1", "diskSizeGB": 5}}]
        if "metrics/disk-usage" in url:
            return 200, [
                {
                    "unit": "bytes",
                    "values": [{"value": 1_000_000}, {"value": 80_000_000}],
                }
            ]
        return 404, {"message": url}

    monkeypatch.setattr("usage_checks._http_get", fake_get)
    result = usage_render()
    assert result["ok"] is True
    bandwidth = result["meters"][0]
    assert bandwidth["used"] == 1.0
    assert bandwidth["limit"] == 5.0
    disk = result["meters"][1]
    assert abs(disk["used"] - 0.08) < 1e-9
    assert disk["limit"] == 5.0
    assert result["level"] == "ok"


def test_usage_level_over_wins() -> None:
    assert (
        usage_level(
            {
                "render": {"level": "ok"},
                "openai": {"level": "warn"},
                "pinecone": {"level": "over"},
            }
        )
        == "over"
    )

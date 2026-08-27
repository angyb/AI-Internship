"""Unit tests for health_checks — no live vendor calls."""

from health_checks import (
    check_gemini,
    pinecone_error_detail,
)


def test_pinecone_egress_limit_message() -> None:
    exc = RuntimeError(
        "[429] Request failed. You've reached your egress limit for the "
        "current month (10000000000 bytes). To continue reading data, "
        "upgrade your plan."
    )
    detail = pinecone_error_detail(exc)
    assert "egress limit" in detail.lower()
    assert "vector search is unavailable" in detail.lower()


def test_pinecone_generic_error_passthrough() -> None:
    detail = pinecone_error_detail(RuntimeError("connection timed out"))
    assert detail == "connection timed out"


def test_pinecone_generic_error_redacts_secrets() -> None:
    detail = pinecone_error_detail(
        RuntimeError("auth failed for Bearer sk-proj-abcdefghijklmnop")
    )
    assert "sk-proj-abcdefghijklmnop" not in detail
    assert "Bearer …" in detail or "sk-…" in detail


def test_check_gemini_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = check_gemini()
    assert result["ok"] is False
    assert "GOOGLE_API_KEY is not set" in result["detail"]


def test_check_gemini_smoke_uses_default_model(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

    def fake_smoke(key: str, model: str) -> tuple[int, dict]:
        assert key == "test-google-key"
        assert model == "gemini-3.6-flash"
        return 200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    monkeypatch.setattr("health_checks._gemini_generate_smoke", fake_smoke)
    monkeypatch.setattr("health_checks._gemini_cache", None)
    result = check_gemini()
    assert result["ok"] is True
    assert "gemini-3.6-flash" in result["detail"]


def test_check_gemini_smoke_success(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

    def fake_smoke(key: str, model: str) -> tuple[int, dict]:
        assert key == "test-google-key"
        assert model == "gemini-2.5-flash"
        return 200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    monkeypatch.setattr("health_checks._gemini_generate_smoke", fake_smoke)
    monkeypatch.setattr("health_checks._gemini_cache", None)
    result = check_gemini()
    assert result["ok"] is True
    assert "gemini-2.5-flash" in result["detail"]
    assert "POST /agent should work" in result["detail"]


def test_check_gemini_smoke_permission_denied(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

    def fake_smoke(_key: str, _model: str) -> tuple[int, dict]:
        return 403, {
            "error": {
                "code": 403,
                "message": "The caller does not have permission",
                "status": "PERMISSION_DENIED",
            }
        }

    monkeypatch.setattr("health_checks._gemini_generate_smoke", fake_smoke)
    monkeypatch.setattr("health_checks._gemini_cache", None)
    result = check_gemini()
    assert result["ok"] is False
    assert "Agent cannot run" in result["detail"]
    assert "permission" in result["detail"].lower()
    assert "GOOGLE_API_KEY on Render" in result["detail"]

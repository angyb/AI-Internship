"""Unit tests for agent API key auth, rate limiting, and operator access."""

from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent_security import (
    _rate_buckets,
    _rate_lock,
    enforce_agent_rate_limit,
    enforce_daily_ask_limit,
    require_operator_access,
    verify_agent_api_key,
)


def _clear_rate_buckets() -> None:
    with _rate_lock:
        _rate_buckets.clear()


def _request(
    client_host: str = "127.0.0.1",
    forwarded: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded:
        headers.append((b"x-forwarded-for", forwarded.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/agent",
        "headers": headers,
        "client": (client_host, 12345),
        "query_string": b"",
        "server": ("test", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_auth_disabled_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    verify_agent_api_key(x_api_key=None, authorization=None)


def test_auth_requires_matching_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_API_KEY", "secret-test-key")
    with pytest.raises(HTTPException) as exc:
        verify_agent_api_key(x_api_key=None, authorization=None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException):
        verify_agent_api_key(x_api_key="wrong", authorization=None)

    verify_agent_api_key(x_api_key="secret-test-key", authorization=None)
    verify_agent_api_key(x_api_key=None, authorization="Bearer secret-test-key")


def test_auth_length_mismatch_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_API_KEY", "short")
    with pytest.raises(HTTPException) as exc:
        verify_agent_api_key(x_api_key="a-much-longer-wrong-key", authorization=None)
    assert exc.value.status_code == 401


def test_rate_limit_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_rate_buckets()
    monkeypatch.setenv("AGENT_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_RATE_LIMIT_PER_MINUTE", "3")
    req = _request("203.0.113.10")
    for _ in range(3):
        enforce_agent_rate_limit(req, x_install_id="unused")
    with pytest.raises(HTTPException) as exc:
        enforce_agent_rate_limit(req, x_install_id="unused")
    assert exc.value.status_code == 429


def test_rate_limit_is_ip_not_install_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_rate_buckets()
    monkeypatch.setenv("AGENT_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_RATE_LIMIT_PER_MINUTE", "2")
    req = _request("198.51.100.9")
    enforce_agent_rate_limit(req, x_install_id="install-a")
    enforce_agent_rate_limit(req, x_install_id="install-b")
    with pytest.raises(HTTPException) as exc:
        enforce_agent_rate_limit(req, x_install_id="install-c")
    assert exc.value.status_code == 429


def test_rate_limit_uses_rightmost_forwarded_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_rate_buckets()
    monkeypatch.setenv("AGENT_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_RATE_LIMIT_PER_MINUTE", "1")
    spoofed = _request("10.0.0.1", forwarded="8.8.8.8, 203.0.113.77")
    trusted = _request("10.0.0.1", forwarded="1.1.1.1, 203.0.113.77")
    enforce_agent_rate_limit(spoofed, x_install_id="a")
    with pytest.raises(HTTPException) as exc:
        enforce_agent_rate_limit(trusted, x_install_id="b")
    assert exc.value.status_code == 429


def test_operator_noop_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_OVERRIDE_CODE", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    require_operator_access(x_override_code=None)
    require_operator_access(x_override_code="anything")


def test_operator_503_on_render_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_OVERRIDE_CODE", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://example.onrender.com")
    with pytest.raises(HTTPException) as exc:
        require_operator_access(x_override_code=None)
    assert exc.value.status_code == 503
    assert "not configured" in str(exc.value.detail)


def test_operator_requires_matching_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_OVERRIDE_CODE", "operator-secret")
    with pytest.raises(HTTPException) as exc:
        require_operator_access(x_override_code=None)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        require_operator_access(x_override_code="wrong")
    assert exc.value.status_code == 401
    require_operator_access(x_override_code="operator-secret")


def test_daily_limit_blocks_then_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_DAILY_ASK_LIMIT", "2")
    monkeypatch.setenv("AGENT_OVERRIDE_CODE", "vip-test-code")
    calls = {"count": 0, "recorded": 0}

    def fake_count(_since):
        return calls["count"]

    def fake_record():
        calls["recorded"] += 1
        calls["count"] += 1

    monkeypatch.setattr("db.database_enabled", lambda: True)
    monkeypatch.setattr("db.count_asks_since", fake_count)
    monkeypatch.setattr("db.record_ask", fake_record)

    enforce_daily_ask_limit(x_override_code=None)
    enforce_daily_ask_limit(x_override_code="")
    with pytest.raises(HTTPException) as exc:
        enforce_daily_ask_limit(x_override_code=None)
    assert exc.value.status_code == 429
    assert "Daily ask limit" in str(exc.value.detail)
    assert calls["recorded"] == 2

    enforce_daily_ask_limit(x_override_code="vip-test-code")
    assert calls["recorded"] == 2


def test_daily_limit_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_DAILY_ASK_LIMIT", "0")
    enforce_daily_ask_limit(x_override_code=None)


def test_daily_limit_503_when_db_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_DAILY_ASK_LIMIT", "100")
    monkeypatch.delenv("AGENT_OVERRIDE_CODE", raising=False)
    monkeypatch.setattr("db.database_enabled", lambda: False)
    with pytest.raises(HTTPException) as exc:
        enforce_daily_ask_limit(x_override_code=None)
    assert exc.value.status_code == 503
    assert "database" in str(exc.value.detail).lower()


def test_daily_limit_override_skips_db_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_DAILY_ASK_LIMIT", "100")
    monkeypatch.setenv("AGENT_OVERRIDE_CODE", "vip-test-code")
    monkeypatch.setattr("db.database_enabled", lambda: False)
    enforce_daily_ask_limit(x_override_code="vip-test-code")


def test_require_session_owner_accepts_hash_and_raw() -> None:
    from db import SessionOwnershipError, _require_session_owner, hash_install_id

    presented = "install-uuid-aaa"
    hashed = hash_install_id(presented)
    _require_session_owner(hashed, presented)
    _require_session_owner(presented, presented)
    with pytest.raises(SessionOwnershipError):
        _require_session_owner(hash_install_id("other-install"), presented)


def test_ingest_clear_index_defaults_false() -> None:
    import main as main_mod

    assert inspect.signature(main_mod.ingest).parameters["clear_index"].default is False

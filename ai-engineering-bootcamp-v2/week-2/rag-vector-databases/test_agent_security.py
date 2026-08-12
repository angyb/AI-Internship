"""Unit tests for agent API key auth and rate limiting."""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent_security import (
    enforce_agent_rate_limit,
    verify_agent_api_key,
)


def _request(client_host: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/agent",
        "headers": [],
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


def test_rate_limit_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_RATE_LIMIT_PER_MINUTE", "3")
    # Fresh bucket key
    install = f"test-install-{os.getpid()}-{id(object())}"
    req = _request()
    for _ in range(3):
        enforce_agent_rate_limit(req, x_install_id=install)
    with pytest.raises(HTTPException) as exc:
        enforce_agent_rate_limit(req, x_install_id=install)
    assert exc.value.status_code == 429

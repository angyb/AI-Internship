"""Tests for per-request agent retrieval mode."""

from __future__ import annotations

import os

from agent_retrieval import (
    reset_retrieval_mode,
    retrieval_lite_enabled,
    set_retrieval_mode,
)


def test_fast_mode_enables_lite():
    reset_retrieval_mode()
    set_retrieval_mode("fast")
    assert retrieval_lite_enabled() is True


def test_slow_mode_disables_lite_even_when_env_true(monkeypatch):
    monkeypatch.setenv("AGENT_LITE_RETRIEVAL", "true")
    reset_retrieval_mode()
    set_retrieval_mode("slow")
    assert retrieval_lite_enabled() is False


def test_env_fallback_when_no_request_mode(monkeypatch):
    monkeypatch.delenv("AGENT_LITE_RETRIEVAL", raising=False)
    reset_retrieval_mode()
    assert retrieval_lite_enabled() is False

    monkeypatch.setenv("AGENT_LITE_RETRIEVAL", "true")
    reset_retrieval_mode()
    assert retrieval_lite_enabled() is True

    os.environ.pop("AGENT_LITE_RETRIEVAL", None)

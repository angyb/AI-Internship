"""Tests for deterministic agent trace checks."""

from __future__ import annotations

from eval_agent import (
    check_citation_present,
    check_fallback_banner,
    check_outcome_appropriate,
    check_used_tool,
    evaluate_trace,
    run_agent_eval,
)
from zearn_faq_bot.constants import FALLBACK_PREFIX, REFUSAL_MESSAGE


def _trace(**overrides):
    base = {
        "id": "t1",
        "question": "What is a Tower Alert?",
        "expected_outcome": "answer",
        "actual_outcome": "answer",
        "answer": "Source: [Tower Alerts](https://help.zearn.org/tower-alerts)",
        "tool_calls": ["search_zearn_doc"],
        "retrieved_document_ids": ["tower-alerts-report"],
        "corpus_chunks": 2,
        "used_web_fallback": False,
        "is_refusal": False,
        "steps": [],
    }
    base.update(overrides)
    return base


def test_check_used_tool_passes_with_search():
    passed, _ = check_used_tool(_trace(tool_calls=["search_zearn_doc"]))
    assert passed


def test_check_used_tool_fails_without_tool():
    passed, reason = check_used_tool(
        _trace(tool_calls=[], answer="Students can add up to 35 students.")
    )
    assert not passed
    assert "without calling" in reason


def test_check_citation_present_fails_without_link():
    passed, reason = check_citation_present(
        _trace(answer="Tower Alerts notify teachers when a student struggles.")
    )
    assert not passed
    assert "missing markdown citation" in reason


def test_check_fallback_banner_requires_prefix():
    passed, _ = check_fallback_banner(
        _trace(
            used_web_fallback=True,
            actual_outcome="web",
            answer=f"{FALLBACK_PREFIX} It is sunny today. Source: [Weather](https://example.com)",
            tool_calls=["google_search_agent"],
        )
    )
    assert passed

    failed, reason = check_fallback_banner(
        _trace(
            used_web_fallback=True,
            actual_outcome="web",
            answer="It is sunny today.",
            tool_calls=["google_search_agent"],
        )
    )
    assert not failed
    assert "missing FALLBACK_PREFIX" in reason


def test_check_outcome_appropriate_catches_wrong_refusal():
    passed, reason = check_outcome_appropriate(
        _trace(
            expected_outcome="answer",
            actual_outcome="refuse",
            is_refusal=True,
            answer=REFUSAL_MESSAGE,
        )
    )
    assert not passed
    assert "Wrong refusal" in reason


def test_evaluate_trace_all_pass():
    row = evaluate_trace(_trace())
    assert row["passed"]
    assert all(item["passed"] for item in row["checks"].values())


def test_run_agent_eval_on_inline_traces():
    result = run_agent_eval([_trace(), _trace(id="t2")])
    assert result["trace_count"] == 2
    assert result["summary"]["trace_count"] == 2
    assert result["summary"]["checks"]["citation_present"]["passed"] == 2

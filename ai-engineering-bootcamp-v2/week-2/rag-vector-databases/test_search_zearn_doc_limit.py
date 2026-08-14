"""Tests for search_zearn_doc per-question call cap."""

from __future__ import annotations

from zearn_faq_bot.constants import MAX_SEARCH_ZEARN_DOC_CALLS
from zearn_faq_bot.tools.search_zearn_doc import reset_search_call_count, search_zearn_doc


def test_search_zearn_doc_call_cap(monkeypatch) -> None:
    reset_search_call_count()
    retrieve_calls = {"n": 0}

    def fake_retrieve(_question: str, **_kwargs):
        retrieve_calls["n"] += 1
        return [], "", [], []

    import main

    monkeypatch.setattr(main, "retrieve_context", fake_retrieve)

    for _ in range(MAX_SEARCH_ZEARN_DOC_CALLS):
        result = search_zearn_doc("tower alerts")
        assert "call limit" not in (result.get("error") or "")

    blocked = search_zearn_doc("tower alerts again")
    assert retrieve_calls["n"] == MAX_SEARCH_ZEARN_DOC_CALLS
    assert blocked.get("chunk_count") == 0
    assert "call limit" in (blocked.get("error") or "")

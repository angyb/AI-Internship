"""Tests for lookup_state_standard exact PDF lookup."""

from __future__ import annotations

from zearn_faq_bot.tools.lookup_state_standard import lookup_state_standard


def test_kansas_invalid_code_not_found_with_similar_suggestions() -> None:
    result = lookup_state_standard("Kansas", "3.OA.A.5")
    assert result["found"] is False
    assert result["requested_code"] == "3.OA.A.5"
    assert result["zearn_mappings"] == []
    assert "3.OA.5" in result["similar_codes_in_state"]


def test_kansas_valid_code_returns_topics_not_lessons() -> None:
    result = lookup_state_standard("Kansas", "3.OA.5")
    assert result["found"] is True
    assert result["matched_code"] == "3.OA.5"
    assert result["zearn_mappings"]
    assert all("Mission" in item for item in result["zearn_mappings"])
    assert not any("Lesson" in item for item in result["zearn_mappings"])
    assert "properties of operations" in result["description"].lower()


def test_colorado_ccss_style_code_returns_lessons() -> None:
    result = lookup_state_standard("Colorado", "3.OA.B.5")
    assert result["found"] is True
    assert result["matched_code"] == "3.OA.B.5"
    assert any("Lesson" in item for item in result["zearn_mappings"])


def test_unknown_state_returns_error() -> None:
    result = lookup_state_standard("Atlantis", "3.OA.5")
    assert result["found"] is False
    assert result.get("error")

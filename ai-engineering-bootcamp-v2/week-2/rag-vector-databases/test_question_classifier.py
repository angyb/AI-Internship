"""Tests for heuristic question-type routing."""

from __future__ import annotations

import json
from pathlib import Path

from question_classifier import ALL_QUESTION_TYPES, classify_question
from question_prompts import (
    get_fact_extraction_template,
    get_grounding_template,
    get_single_step_template,
)


def test_golden_set_routing() -> None:
    golden = json.loads(
        Path(__file__).resolve().parent.joinpath("golden_set.json").read_text(encoding="utf-8")
    )
    # Expected route for each question currently in golden_set.json. Keep in sync
    # when the golden set changes.
    expected = {
        "How many students can I add to my class?": "general",
        "How do I add students to my class?": "how_to",
        "What causes a Tower Alert and what is its purpose?": "report",
        "What is LEAP?": "research",
        "How has Zearn incorporated the science of learning into its product?": "general",
        "Who can get a free Zearn account?": "general",
    }
    golden_questions = {item["question"] for item in golden}
    assert golden_questions == set(expected), (
        "expected routing map is out of sync with golden_set.json: "
        f"missing={golden_questions - set(expected)}, extra={set(expected) - golden_questions}"
    )
    for item in golden:
        q = item["question"]
        assert classify_question(q) == expected[q], f"{q!r} -> {classify_question(q)!r}"


def test_every_type_has_templates() -> None:
    for question_type in ALL_QUESTION_TYPES:
        assert get_fact_extraction_template(question_type)
        assert get_grounding_template(question_type)
        assert get_single_step_template(question_type)


def test_list_features_routing() -> None:
    q = "Give me a succinct list of accessibility features — feature names only."
    assert classify_question(q) == "list_features"


def test_troubleshooting_routing() -> None:
    assert classify_question("Zearn won't load on my iPad") == "troubleshooting"

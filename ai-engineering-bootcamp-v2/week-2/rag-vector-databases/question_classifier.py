"""Lightweight regex/heuristic question-type routing — no extra LLM call."""

from __future__ import annotations

import os
import re
from typing import Literal

QuestionType = Literal[
    "how_to",
    "research",
    "report",
    "comparison",
    "definition",
    "affirmation",
    "integration",
    "checklist_orientation",
    "list_features",
    "parent_family",
    "troubleshooting",
    "yes_no",
    "requirements",
    "permissions",
    "policy",
    "navigation",
    "general",
]

ALL_QUESTION_TYPES: tuple[QuestionType, ...] = (
    "how_to",
    "research",
    "report",
    "comparison",
    "definition",
    "affirmation",
    "integration",
    "checklist_orientation",
    "list_features",
    "parent_family",
    "troubleshooting",
    "yes_no",
    "requirements",
    "permissions",
    "policy",
    "navigation",
    "general",
)

# Ordered rules — first match wins (most specific patterns first).
_CLASSIFICATION_RULES: list[tuple[QuestionType, re.Pattern[str]]] = [
    (
        "list_features",
        re.compile(
            r"names?\s+only|feature\s+names|list\s+of\s+\w+|succinct\s+list|"
            r"bullet\s+list\s+of|without\s+descriptions?",
            re.I,
        ),
    ),
    (
        "comparison",
        re.compile(
            r"\bcompare\b|\bdifference\s+between\b|\bvs\.?\b|\bversus\b|"
            r"which\s+\w+\s+accounts?\s+|individual\s+vs|school\s+vs|"
            r"which\s+accounts?\s+are\s+free|\bfree\s+accounts?\b",
            re.I,
        ),
    ),
    (
        "affirmation",
        re.compile(
            r"\bbased\s+on\b|\bgrounded\s+in\b|\blearning\s+science\b|"
            r"\bresearch[\-\s]based\b|\bevidence[\-\s]based\b|"
            r"\bis\s+\w+\s+(designed|built|grounded|based)\b",
            re.I,
        ),
    ),
    (
        "troubleshooting",
        re.compile(
            r"troubleshoot|won'?t\s+(load|work|open|print)|can'?t\s+(log|sign|access)|"
            r"not\s+working|doesn'?t\s+work|\berror\b|\bfix\b|\bissue\b|"
            r"blank\s+(page|report)|not\s+printing",
            re.I,
        ),
    ),
    (
        "parent_family",
        re.compile(
            r"\bparent\b|\bfamily\b|\bchild'?s?\b|\bhomeschool|\bat\s+home\b|"
            r"my\s+child",
            re.I,
        ),
    ),
    (
        "integration",
        re.compile(
            r"\bclever\b|\bclasslink\b|\boneroster\b|\broster(?:ing|er)?\b|"
            r"\bsync\b|\bsso\b|\bmerge\s+accounts?\b|\bspreadsheet\s+roster",
            re.I,
        ),
    ),
    (
        "permissions",
        re.compile(
            r"\bpermission\b|\bco-?teacher\b|\badmin\s+role\b|\baccess\s+level\b|"
            r"what\s+can\s+(a\s+)?(admin|teacher|co-?teacher)",
            re.I,
        ),
    ),
    (
        "requirements",
        re.compile(
            r"\brequirement\b|\bcompatible\b|\bbrowser\b|\bdevice\b|\bbandwidth\b|"
            r"\bandroid\b|\bipad\b|\btechnology\b|\bsystem\s+requirements?",
            re.I,
        ),
    ),
    (
        "policy",
        re.compile(
            r"\bprivacy\b|\bpolicy\b|\bcookie\b|\bferpa\b|\bgdpr\b|\bsub-?processor",
            re.I,
        ),
    ),
    (
        "navigation",
        re.compile(
            r"\bwhere\s+(do|can|should)\s+i\b|\bwhere\s+to\s+find\b|"
            r"\bhow\s+do\s+i\s+find\b|\blocate\b.*\breport\b",
            re.I,
        ),
    ),
    (
        "checklist_orientation",
        re.compile(
            r"\bchecklist\b|\borient(?:ation)?\b|\bgetting\s+started\b|"
            r"\bfirst\s+steps?\b|\boverview\s+of\s+implement",
            re.I,
        ),
    ),
    (
        "research",
        re.compile(
            r"\bstudy\b|\bresearch\b|\befficacy\b|\bimpact\s+study\b|\bfindings?\b|"
            r"\bstatistically\b|\bLEAP\b|\bSTAAR\b|\bassessment\b.*\b(state|Louisiana|Texas)\b|"
            r"what\s+did\s+the\s+\w+\s+study\b",
            re.I,
        ),
    ),
    (
        "report",
        re.compile(
            r"\breport\b|\bliveview\b|\bsnapshot\b|\bpace\s+report\b|"
            r"\bprogress\s+report\b|\btower\s+alert\b|\bsprint\s+alert\b|"
            r"what\s+does\s+the\s+\w+\s+report\s+show",
            re.I,
        ),
    ),
    (
        "how_to",
        re.compile(
            r"^how\s+(?:do\s+i|to|can\s+i)\b|\bsteps?\s+to\b|"
            r"^how\s+should\s+i\b|\bwalk\s+me\s+through\b",
            re.I,
        ),
    ),
    (
        "yes_no",
        re.compile(
            r"^(?:is|are|can|do|does|will|should|am)\s+\w",
            re.I,
        ),
    ),
    (
        "definition",
        re.compile(
            r"^what\s+(?:is|are|does)\b|^explain\s+what\b|^define\b",
            re.I,
        ),
    ),
]


def question_routing_enabled() -> bool:
    return os.getenv("QUESTION_ROUTING_ENABLED", "true").lower() != "false"


def prompt_profile_override() -> QuestionType | None:
    """Force a question type via PROMPT_PROFILE env (testing / A-B)."""
    raw = os.getenv("PROMPT_PROFILE", "").strip().lower()
    if not raw or raw in ("auto", "default", "general"):
        return None
    if raw in ALL_QUESTION_TYPES:
        return raw  # type: ignore[return-value]
    return None


def classify_question(question: str) -> QuestionType:
    """Classify a user question into a prompt template type."""
    override = prompt_profile_override()
    if override is not None:
        return override

    if not question_routing_enabled():
        return "general"

    text = question.strip()
    if not text:
        return "general"

    for question_type, pattern in _CLASSIFICATION_RULES:
        if pattern.search(text):
            return question_type

    return "general"

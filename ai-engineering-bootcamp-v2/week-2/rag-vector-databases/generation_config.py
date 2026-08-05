"""Env toggles for answer verbosity, citations, and shared prompt rule blocks."""

from __future__ import annotations

import os
from typing import Literal

from env_utils import bool_env

AnswerVerbosity = Literal["concise", "complete"]

_FIDELITY_RULES = """\
- Prefer verbatim phrases from the context when they directly answer the question.
- Do not add navigation paths, prerequisites, account comparisons, or extra sections unless the question explicitly asks for them."""

_CONFLICT_RESOLUTION_RULES = """\
- When chunks conflict on the same fact, prefer the most specific wording: if one chunk states an exact number or count and another uses a vague quantifier (e.g. "multiple", "several", "many"), use the numeric phrasing."""

_CONCISE_VERBOSITY_RULES = """\
- Answer only what the question asks; omit tangential details from other chunks.
- Follow the question's requested format (e.g. numbered steps for how-to, bullet list when requested)."""

_COMPLETE_VERBOSITY_RULES = """\
- Include triggers, conditions, limits, and alternative paths when relevant to the question.
- When multiple facts describe the same concept, combine them without dropping specifics.
- Follow the question's requested format when obvious (e.g. numbered steps for how-to questions)."""

_CONCISE_EXTRACTION_SCOPE_RULES = """\
- Extract only facts needed to answer the question; skip tangential details."""

_COMPLETE_EXTRACTION_SCOPE_RULES = """\
- Read every chunk before writing; include all distinct facts relevant to the question."""

_CITATION_RULES = """\
- Cite each fact with a markdown link using the title and url from the context, e.g. [Tower Alerts Report](https://help.zearn.org/...).
- Use the exact title and url shown in each context block; do not invent links.
- When a chunk has no url, cite with the title only in brackets, e.g. [Supporting Eureka Math 2]."""


def answer_verbosity() -> AnswerVerbosity:
    value = os.getenv("ANSWER_VERBOSITY", "concise").strip().lower()
    if value == "complete":
        return "complete"
    return "concise"


def citations_enabled() -> bool:
    return bool_env("CITATIONS_ENABLED", False)


def prompt_conflict_resolution_enabled() -> bool:
    return bool_env("PROMPT_CONFLICT_RESOLUTION_ENABLED", True)


def fidelity_rules_block() -> str:
    rules = _FIDELITY_RULES
    if prompt_conflict_resolution_enabled():
        rules = f"{rules}\n{_CONFLICT_RESOLUTION_RULES}"
    return rules


def verbosity_rules_block() -> str:
    if answer_verbosity() == "complete":
        return _COMPLETE_VERBOSITY_RULES
    return _CONCISE_VERBOSITY_RULES


def extraction_scope_rules_block() -> str:
    if answer_verbosity() == "complete":
        return _COMPLETE_EXTRACTION_SCOPE_RULES
    return _CONCISE_EXTRACTION_SCOPE_RULES


def citation_rules_block() -> str:
    if citations_enabled():
        return _CITATION_RULES
    return ""


def prompt_substitution_vars(*, for_extraction: bool = False) -> dict[str, str]:
    """Template substitution keys shared by question_prompts."""
    return {
        "FIDELITY_RULES": fidelity_rules_block(),
        "VERBOSITY_RULES": "" if for_extraction else verbosity_rules_block(),
        "EXTRACTION_SCOPE_RULES": extraction_scope_rules_block() if for_extraction else "",
        "CITATION_RULES": citation_rules_block(),
    }

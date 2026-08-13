"""Answer post-processing helpers for the Zearn support agent."""

from __future__ import annotations

import re

_BULLETED_SOURCES = re.compile(
    r"(?:\*\*Sources:\*\*|Sources:)\s*\n"
    r"(?:(?:[-*]\s+|\d+\.\s+)\[[^\]]+\]\([^)]+\)\s*\n?)+",
    re.IGNORECASE,
)
_TRAILING_INLINE_SOURCE = re.compile(
    r"\n---\s*\n+Source:\s*[^\n]+\s*$",
    re.IGNORECASE,
)
_TRAILING_SOURCE_LINE = re.compile(
    r"\n+Source:\s*[^\n]+\s*$",
    re.IGNORECASE,
)


def strip_duplicate_inline_sources(answer: str) -> str:
    """Drop a trailing inline ``Source:`` line when a bulleted Sources section exists."""
    text = (answer or "").strip()
    if not _BULLETED_SOURCES.search(text):
        return text
    text = _TRAILING_INLINE_SOURCE.sub("", text)
    text = _TRAILING_SOURCE_LINE.sub("", text)
    return text.strip()

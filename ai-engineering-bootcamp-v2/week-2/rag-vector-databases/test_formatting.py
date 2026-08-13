"""Tests for answer formatting helpers."""

from zearn_faq_bot.formatting import strip_duplicate_inline_sources

_SAMPLE = """Zearn offers state standards PDFs for many states.

**Sources:**
- [Zearn State Standards Kansas (PDF)](https://example.com/ks.pdf)
- [Zearn State Standards Colorado (PDF)](https://example.com/co.pdf)
- [Zearn State Standards New York (PDF)](https://example.com/ny.pdf)

---
Source: [Zearn State Standards Kansas (PDF)](https://example.com/ks.pdf), [Zearn State Standards Colorado (PDF)](https://example.com/co.pdf), [Zearn State Standards New York (PDF)](https://example.com/ny.pdf)"""


def test_strip_duplicate_inline_sources_after_bulleted_section():
    cleaned = strip_duplicate_inline_sources(_SAMPLE)
    assert "**Sources:**" in cleaned
    assert cleaned.count("Zearn State Standards Kansas") == 1
    assert "\nSource:" not in cleaned
    assert "---" not in cleaned


def test_keeps_inline_source_when_no_bulleted_section():
    answer = "Tower Alerts notify teachers. Source: [Tower Alerts](https://help.zearn.org/tower-alerts)"
    assert strip_duplicate_inline_sources(answer) == answer


def test_keeps_bulleted_sources_only():
    answer = """Answer text.

**Sources:**
- [Boosts](https://help.zearn.org/boosts)"""
    assert strip_duplicate_inline_sources(answer) == answer

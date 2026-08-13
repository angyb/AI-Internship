"""Deterministic pass/fail checks for Zearn ADK agent traces (Week 4 TRACE Path A)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from zearn_faq_bot.constants import FALLBACK_PREFIX, REFUSAL_MESSAGE

from agent_trace import DEFAULT_TRACES, load_traces

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
KNOWN_TOOLS = {"search_zearn_doc", "google_search_agent", "google_search"}
DEFAULT_LENGTH_BUDGET = 2500

CheckFn = Callable[[dict[str, Any]], tuple[bool, str]]


def _answer_text(trace: dict[str, Any]) -> str:
    return str(trace.get("answer") or "").strip()


def check_used_tool(trace: dict[str, Any]) -> tuple[bool, str]:
    tool_calls = trace.get("tool_calls") or []
    if any(tool in KNOWN_TOOLS for tool in tool_calls):
        return True, "At least one search tool was called."
    if trace.get("is_refusal"):
        return True, "Refusal without tool use is acceptable."
    return False, "Answered without calling search_zearn_doc or google_search_agent."


def check_citation_present(trace: dict[str, Any]) -> tuple[bool, str]:
    answer = _answer_text(trace)
    if trace.get("is_refusal"):
        return True, "Refusal — citation not required."
    if trace.get("used_web_fallback") or trace.get("actual_outcome") == "web":
        if MARKDOWN_LINK_RE.search(answer):
            return True, "Web answer includes a markdown link."
        return False, "Web fallback answer missing a markdown source link."
    corpus_chunks = int(trace.get("corpus_chunks") or 0)
    retrieved = trace.get("retrieved_document_ids") or []
    if corpus_chunks <= 0 and not retrieved:
        return True, "No corpus chunks retrieved — citation not required."
    if MARKDOWN_LINK_RE.search(answer):
        return True, "Corpus answer includes a markdown citation link."
    return False, "Corpus-backed answer missing markdown citation link."


def check_fallback_banner(trace: dict[str, Any]) -> tuple[bool, str]:
    answer = _answer_text(trace)
    used_web = bool(trace.get("used_web_fallback"))
    has_prefix = answer.startswith(FALLBACK_PREFIX)
    if used_web and not has_prefix:
        return False, "Used google_search_agent but missing FALLBACK_PREFIX opener."
    if has_prefix and not used_web:
        return False, "FALLBACK_PREFIX present without a google_search_agent call."
    return True, "Web fallback banner matches tool usage."


def check_outcome_appropriate(trace: dict[str, Any]) -> tuple[bool, str]:
    expected = str(trace.get("expected_outcome") or "answer").strip().lower()
    actual = str(trace.get("actual_outcome") or "answer").strip().lower()
    if expected == actual:
        return True, f"Expected {expected}; got {actual}."
    if expected == "refuse" and actual == "refuse":
        return True, "Correctly refused."
    if expected == "web" and actual == "web":
        return True, "Correctly used web fallback."
    if expected == "answer" and actual == "answer":
        return True, "Correctly answered from agent."
    if expected == "answer" and actual == "refuse":
        return False, "Wrong refusal — corpus should answer this question."
    if expected == "web" and actual == "refuse":
        return False, "Wrong refusal — should attempt web fallback."
    if expected == "refuse" and actual in ("answer", "web"):
        return False, f"Should refuse off-topic question but returned {actual}."
    if expected == "answer" and actual == "web":
        return False, "Used web fallback for a question answerable from Zearn docs."
    return False, f"Expected {expected}; got {actual}."


def check_length_budget(
    trace: dict[str, Any],
    *,
    max_chars: int = DEFAULT_LENGTH_BUDGET,
) -> tuple[bool, str]:
    answer = _answer_text(trace)
    length = len(answer)
    if length <= max_chars:
        return True, f"Answer length {length} <= {max_chars}."
    return False, f"Answer length {length} exceeds budget of {max_chars}."


CHECKS: list[tuple[str, CheckFn]] = [
    ("used_tool", check_used_tool),
    ("citation_present", check_citation_present),
    ("fallback_banner", check_fallback_banner),
    ("outcome_appropriate", check_outcome_appropriate),
    ("length_budget", check_length_budget),
]


def evaluate_trace(trace: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for name, fn in CHECKS:
        passed, reason = fn(trace)
        checks[name] = {"passed": passed, "reason": reason}

    all_passed = all(item["passed"] for item in checks.values())
    return {
        "id": trace.get("id", ""),
        "question": trace.get("question", ""),
        "expected_outcome": trace.get("expected_outcome", ""),
        "actual_outcome": trace.get("actual_outcome", ""),
        "checks": checks,
        "passed": all_passed,
    }


def summarize_checks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {name: {"passed": 0, "failed": 0, "pass_rate": 0.0} for name, _ in CHECKS}
    for row in rows:
        for name, result in (row.get("checks") or {}).items():
            if name not in totals:
                continue
            if result.get("passed"):
                totals[name]["passed"] += 1
            else:
                totals[name]["failed"] += 1
    count = len(rows)
    for name in totals:
        passed = totals[name]["passed"]
        totals[name]["pass_rate"] = round(passed / count, 4) if count else 0.0
    all_passed = sum(1 for row in rows if row.get("passed"))
    return {
        "trace_count": count,
        "all_checks_passed": all_passed,
        "all_checks_pass_rate": round(all_passed / count, 4) if count else 0.0,
        "checks": totals,
    }


def run_agent_eval(
    traces: list[dict[str, Any]] | None = None,
    *,
    traces_path: Path | str = DEFAULT_TRACES,
) -> dict[str, Any]:
    records = traces if traces is not None else load_traces(traces_path)
    rows = [evaluate_trace(trace) for trace in records]
    return {
        "traces_file": str(traces_path),
        "trace_count": len(records),
        "summary": summarize_checks(rows),
        "rows": rows,
    }


def save_eval_result(result: dict[str, Any], path: Path | str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_eval_result(path: Path | str) -> dict[str, Any] | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run deterministic agent trace checks.")
    parser.add_argument(
        "--traces",
        default=str(DEFAULT_TRACES),
        help="Path to zearn_agent_traces.jsonl",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write JSON results",
    )
    args = parser.parse_args()

    result = run_agent_eval(traces_path=args.traces)
    if args.output:
        save_eval_result(result, args.output)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()

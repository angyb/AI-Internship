"""Capture ADK agent runs as JSONL traces for Week 4 TRACE Path A."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zearn_faq_bot.constants import FALLBACK_PREFIX, REFUSAL_MESSAGE

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "trace_questions.json"
DEFAULT_TRACES = Path(__file__).resolve().parent / "traces" / "zearn_agent_traces.jsonl"
DEFAULT_OPEN_CODING = Path(__file__).resolve().parent / "traces" / "open_coding.csv"

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")


def load_trace_questions(path: Path | str = DEFAULT_QUESTIONS) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("trace_questions.json must be a JSON array")
    return data


def load_traces(path: Path | str = DEFAULT_TRACES) -> list[dict[str, Any]]:
    trace_path = Path(path)
    if not trace_path.exists():
        return []
    traces: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            traces.append(json.loads(line))
    return traces


def save_traces(traces: list[dict[str, Any]], path: Path | str = DEFAULT_TRACES) -> None:
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in traces:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _parse_observe_result(result: str | None) -> dict[str, Any]:
    if not result:
        return {"chunk_count": 0, "document_ids": [], "sources": []}
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        return {"chunk_count": 0, "document_ids": [], "sources": []}
    if not isinstance(parsed, dict):
        return {"chunk_count": 0, "document_ids": [], "sources": []}
    document_ids = [
        str(doc_id).strip()
        for doc_id in (parsed.get("document_ids") or [])
        if str(doc_id).strip()
    ]
    return {
        "chunk_count": int(parsed.get("chunk_count") or 0),
        "document_ids": document_ids,
        "sources": parsed.get("sources") or [],
        "error": parsed.get("error"),
    }


def summarize_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    tool_calls: list[str] = []
    retrieved_document_ids: list[str] = []
    used_web_fallback = False
    corpus_chunks = 0

    for step in steps:
        phase = step.get("phase")
        tool = step.get("tool") or ""
        if phase == "Act" and tool:
            tool_calls.append(tool)
            if tool in ("google_search_agent", "google_search"):
                used_web_fallback = True
        if phase == "Observe" and tool == "search_zearn_doc":
            summary = _parse_observe_result(step.get("result"))
            corpus_chunks += int(summary.get("chunk_count") or 0)
            for doc_id in summary.get("document_ids") or []:
                if doc_id not in retrieved_document_ids:
                    retrieved_document_ids.append(doc_id)

    return {
        "tool_calls": tool_calls,
        "retrieved_document_ids": retrieved_document_ids,
        "used_web_fallback": used_web_fallback,
        "corpus_chunks": corpus_chunks,
    }


def classify_answer(answer: str, summary: dict[str, Any]) -> str:
    text = (answer or "").strip()
    if text == REFUSAL_MESSAGE or text.startswith(REFUSAL_MESSAGE):
        return "refuse"
    if summary.get("used_web_fallback") or text.startswith(FALLBACK_PREFIX):
        return "web"
    return "answer"


def build_trace_record(
    item: dict[str, Any],
    answer: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = summarize_steps(steps)
    answer_text = (answer or "").strip()
    actual_outcome = classify_answer(answer_text, summary)
    return {
        "id": item["id"],
        "question": item["question"],
        "expected_outcome": item.get("expected_outcome", "answer"),
        "note": item.get("note", ""),
        "answer": answer_text,
        "steps": steps,
        "tool_calls": summary["tool_calls"],
        "retrieved_document_ids": summary["retrieved_document_ids"],
        "corpus_chunks": summary["corpus_chunks"],
        "used_web_fallback": summary["used_web_fallback"],
        "is_refusal": actual_outcome == "refuse",
        "actual_outcome": actual_outcome,
        "has_markdown_link": bool(MARKDOWN_LINK_RE.search(answer_text)),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def capture_traces(
    questions_path: Path | str = DEFAULT_QUESTIONS,
    output_path: Path | str = DEFAULT_TRACES,
    *,
    question_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    from zearn_support_agent import run_zearn_agent

    questions = load_trace_questions(questions_path)
    if question_ids:
        allowed = set(question_ids)
        questions = [q for q in questions if q.get("id") in allowed]

    traces: list[dict[str, Any]] = []
    for item in questions:
        answer, steps, _usage = run_zearn_agent(item["question"])
        traces.append(build_trace_record(item, answer, steps))

    save_traces(traces, output_path)
    export_open_coding_scaffold(traces, DEFAULT_OPEN_CODING)
    return traces


def export_open_coding_scaffold(
    traces: list[dict[str, Any]],
    output_path: Path | str = DEFAULT_OPEN_CODING,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "question",
                "expected_outcome",
                "actual_outcome",
                "notes",
                "pass_fail",
                "failure_label",
            ],
        )
        writer.writeheader()
        for trace in traces:
            writer.writerow(
                {
                    "id": trace.get("id", ""),
                    "question": trace.get("question", ""),
                    "expected_outcome": trace.get("expected_outcome", ""),
                    "actual_outcome": trace.get("actual_outcome", ""),
                    "notes": "",
                    "pass_fail": "",
                    "failure_label": "",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Zearn agent traces to JSONL.")
    parser.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS),
        help="Path to trace_questions.json",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_TRACES),
        help="Path to write zearn_agent_traces.jsonl",
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        help="Optional subset of question ids to capture",
    )
    args = parser.parse_args()

    traces = capture_traces(args.questions, args.output, question_ids=args.ids or None)
    print(f"Captured {len(traces)} traces -> {args.output}")


if __name__ == "__main__":
    main()

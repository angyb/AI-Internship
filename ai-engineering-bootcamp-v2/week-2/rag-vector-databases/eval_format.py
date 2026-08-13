"""Shared formatting for golden-set eval reports (CLI, Streamlit, agent summaries)."""

from __future__ import annotations

import re
from typing import Any

# Strip grounding citations from displayed answers (RAGAS still scores the raw answer).
_ANSWER_CITATION_RE = re.compile(
    r"\s*(?:\[[^\]]+\]\([^)]+\)|\[(?:document_id:\s*[^\]]+|[^\]:]+:\s*[^\]]+)\])\.?"
)


def format_answer_for_display(answer: str) -> str:
    cleaned = _ANSWER_CITATION_RE.sub("", answer)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    lines = [re.sub(r"  +", " ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line)


def unique_chunk_ids(chunk_ids: list[str]) -> list[str]:
    """Preserve order, drop duplicates (neighbor merge can repeat ids)."""
    seen: set[str] = set()
    unique: list[str] = []
    for chunk_id in chunk_ids:
        if chunk_id and chunk_id not in seen:
            seen.add(chunk_id)
            unique.append(chunk_id)
    return unique


def questions_and_answers_rows(questions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One row per golden-set question for the Q&A table."""
    rows: list[dict[str, str]] = []
    for item in questions:
        chunk_ids = unique_chunk_ids(item.get("chunk_ids") or [])
        rows.append(
            {
                "Question": item["question"],
                "Reference": item["reference"],
                "Answer": format_answer_for_display(item.get("answer", "")),
                "Chunk_IDs": "\n".join(chunk_ids) if chunk_ids else "—",
            }
        )
    return rows


def _markdown_cell(text: str) -> str:
    """Escape pipes and preserve line breaks for markdown table cells."""
    return text.strip().replace("|", "\\|").replace("\n", "<br>")


def _format_bool(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    return str(value)


def retrieval_config_rows(config: dict[str, Any]) -> list[dict[str, str]]:
    rows = [
        {"Setting": "chunk_size", "Value": str(config.get("chunk_size", "—"))},
        {"Setting": "chunk_overlap", "Value": str(config.get("chunk_overlap", "—"))},
        {"Setting": "k", "Value": str(config.get("k", "—"))},
        {"Setting": "fetch_k", "Value": str(config.get("fetch_k", "—"))},
        {"Setting": "max_per_document", "Value": str(config.get("max_per_document", "—"))},
        {"Setting": "hybrid_search", "Value": _format_bool(config.get("hybrid_search"))},
        {"Setting": "rerank_enabled", "Value": _format_bool(config.get("rerank_enabled"))},
        {"Setting": "rerank_candidates", "Value": str(config.get("rerank_candidates", "—"))},
        {"Setting": "rerank_model", "Value": str(config.get("rerank_model", "—"))},
        {
            "Setting": "neighbor_chunks_enabled",
            "Value": _format_bool(config.get("neighbor_chunks_enabled")),
        },
        {
            "Setting": "neighbor_chunk_radius",
            "Value": str(config.get("neighbor_chunk_radius", "—")),
        },
        {
            "Setting": "neighbor_merge_enabled",
            "Value": _format_bool(config.get("neighbor_merge_enabled")),
        },
        {
            "Setting": "max_context_chunks_enabled",
            "Value": _format_bool(config.get("max_context_chunks_enabled")),
        },
        {
            "Setting": "max_context_chunks",
            "Value": str(config.get("max_context_chunks", "—")),
        },
        {
            "Setting": "two_step_generation",
            "Value": _format_bool(config.get("two_step_generation")),
        },
        {
            "Setting": "question_routing_enabled",
            "Value": _format_bool(config.get("question_routing_enabled")),
        },
        {
            "Setting": "answer_verbosity",
            "Value": str(config.get("answer_verbosity", "—")),
        },
        {
            "Setting": "citations_enabled",
            "Value": _format_bool(config.get("citations_enabled")),
        },
        {
            "Setting": "relevance_filter_enabled",
            "Value": _format_bool(config.get("relevance_filter_enabled")),
        },
        {
            "Setting": "relevance_min_score_gap",
            "Value": str(config.get("relevance_min_score_gap", "—")),
        },
        {
            "Setting": "relevance_min_chunks",
            "Value": str(config.get("relevance_min_chunks", "—")),
        },
        {
            "Setting": "prompt_conflict_resolution_enabled",
            "Value": _format_bool(config.get("prompt_conflict_resolution_enabled")),
        },
        {
            "Setting": "context_order_by_rerank_score",
            "Value": _format_bool(config.get("context_order_by_rerank_score")),
        },
        {
            "Setting": "answer_model",
            "Value": str(config.get("answer_model", "—")),
        },
        {
            "Setting": "extraction_model",
            "Value": str(config.get("extraction_model", "—")),
        },
        {
            "Setting": "embedding_model",
            "Value": str(config.get("embedding_model", "—")),
        },
        {
            "Setting": "ragas_judge_model",
            "Value": str(config.get("ragas_judge_model", "—")),
        },
        {
            "Setting": "generation_temperature",
            "Value": str(config.get("generation_temperature", "—")),
        },
    ]
    excluded = config.get("exclude_document_ids") or []
    if excluded:
        rows.append(
            {
                "Setting": "exclude_document_ids",
                "Value": ", ".join(excluded),
            }
        )
    return rows


def averages_rows(averages: dict[str, Any]) -> list[dict[str, str]]:
    faith_avg = averages.get("faithfulness")
    corr_avg = averages.get("answer_correctness")
    return [
        {
            "Metric": "retrieval_hit",
            "Score": (
                f"{averages['retrieval_hit']:.2%} "
                f"({averages['retrieval_hits']}/{averages['question_count']})"
            ),
        },
        {
            "Metric": "faithfulness",
            "Score": f"{faith_avg:.4f}" if faith_avg is not None else "—",
        },
        {
            "Metric": "answer_correctness",
            "Score": f"{corr_avg:.4f}" if corr_avg is not None else "—",
        },
    ]


def per_question_score_rows(questions: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in questions:
        faith = item.get("faithfulness")
        correctness = item.get("answer_correctness")
        rows.append(
            {
                "Question": item["question"],
                "Hit": "✅" if item.get("retrieval_hit") else "❌",
                "Faithfulness": f"{faith:.2f}" if faith is not None else "—",
                "Correctness": f"{correctness:.2f}" if correctness is not None else "—",
            }
        )
    return rows


def format_markdown_table(headers: list[str], rows: list[dict[str, str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [_markdown_cell(str(row[h])) for h in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


QA_TABLE_HEADERS = ["Question", "Reference", "Answer", "Chunk_IDs"]


def format_questions_and_answers_table_markdown(questions: list[dict[str, Any]]) -> str:
    rows = questions_and_answers_rows(questions)
    return format_markdown_table(QA_TABLE_HEADERS, rows)


def agent_check_summary_rows(summary: dict[str, Any]) -> list[dict[str, str]]:
    checks = summary.get("checks") or {}
    rows: list[dict[str, str]] = []
    for name, stats in checks.items():
        passed = int(stats.get("passed") or 0)
        failed = int(stats.get("failed") or 0)
        total = passed + failed
        rate = stats.get("pass_rate")
        rows.append(
            {
                "Check": name,
                "Pass rate": f"{rate:.1%}" if isinstance(rate, (int, float)) else "—",
                "Passed": str(passed),
                "Failed": str(failed),
                "Total": str(total),
            }
        )
    rows.insert(
        0,
        {
            "Check": "all_checks",
            "Pass rate": f"{summary.get('all_checks_pass_rate', 0):.1%}",
            "Passed": str(summary.get("all_checks_passed", 0)),
            "Failed": str(
                int(summary.get("trace_count") or 0)
                - int(summary.get("all_checks_passed") or 0)
            ),
            "Total": str(summary.get("trace_count", 0)),
        },
    )
    return rows


def agent_check_comparison_rows(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if not before or not after:
        return []
    before_checks = (before.get("summary") or {}).get("checks") or {}
    after_checks = (after.get("summary") or {}).get("checks") or {}
    rows: list[dict[str, str]] = []
    for name in sorted(set(before_checks) | set(after_checks)):
        b_rate = before_checks.get(name, {}).get("pass_rate")
        a_rate = after_checks.get(name, {}).get("pass_rate")
        delta = None
        if isinstance(b_rate, (int, float)) and isinstance(a_rate, (int, float)):
            delta = a_rate - b_rate
        rows.append(
            {
                "Check": name,
                "Before": f"{b_rate:.1%}" if isinstance(b_rate, (int, float)) else "—",
                "After": f"{a_rate:.1%}" if isinstance(a_rate, (int, float)) else "—",
                "Delta": f"{delta:+.1%}" if delta is not None else "—",
            }
        )
    return rows


def agent_trace_check_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    table_rows: list[dict[str, str]] = []
    for row in rows:
        checks = row.get("checks") or {}
        failed = [name for name, item in checks.items() if not item.get("passed")]
        table_rows.append(
            {
                "ID": row.get("id", ""),
                "Question": row.get("question", ""),
                "Expected": row.get("expected_outcome", ""),
                "Actual": row.get("actual_outcome", ""),
                "Pass": "✅" if row.get("passed") else "❌",
                "Failed checks": ", ".join(failed) if failed else "—",
            }
        )
    return table_rows


def format_eval_report_markdown(result: dict[str, Any]) -> str:
    """Full markdown eval report including Q&A table."""
    config = result.get("config", {})
    averages = result.get("averages", {})
    questions = result.get("questions", [])

    parts = [
        "### Retrieval config",
        format_markdown_table(["Setting", "Value"], retrieval_config_rows(config)),
        "",
        "### Averages",
        format_markdown_table(["Metric", "Score"], averages_rows(averages)),
        "",
        "### Per-question scores",
        format_markdown_table(
            ["Question", "Hit", "Faithfulness", "Correctness"],
            per_question_score_rows(questions),
        ),
        "",
        "### Questions and answers",
        format_questions_and_answers_table_markdown(questions),
    ]
    return "\n".join(parts)

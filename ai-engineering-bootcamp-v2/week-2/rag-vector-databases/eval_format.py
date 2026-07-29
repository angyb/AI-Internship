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

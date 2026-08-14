#!/usr/bin/env python3
"""POST /agent for golden-set questions and print a latency breakdown table.

Usage:
  python agent_baseline_timings.py
  python agent_baseline_timings.py --base-url https://ai-internship-i3lw.onrender.com
  AGENT_API_KEY=secret python agent_baseline_timings.py --limit 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

DEFAULT_BASE = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
GOLDEN_PATH = _ROOT / "golden_set.json"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "X-Install-Id": str(uuid.uuid4())}
    api_key = os.getenv("AGENT_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _load_questions(limit: int) -> list[str]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    questions = [str(item.get("question", "")).strip() for item in data if item.get("question")]
    return questions[:limit]


def _format_row(cells: list[str], widths: list[int]) -> str:
    return " | ".join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture /agent latency baselines.")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="RAG API base URL")
    parser.add_argument("--limit", type=int, default=5, help="Number of golden questions")
    parser.add_argument("--timeout", type=float, default=180.0, help="Request timeout seconds")
    args = parser.parse_args()

    if not GOLDEN_PATH.is_file():
        print(f"Missing {GOLDEN_PATH}", file=sys.stderr)
        return 1

    questions = _load_questions(max(1, args.limit))
    base = args.base_url.rstrip("/")
    headers = _headers()

    rows: list[dict[str, object]] = []
    span_names: set[str] = set()

    print(f"Target: {base}/agent ({len(questions)} questions)\n")

    with httpx.Client(timeout=args.timeout) as client:
        for index, question in enumerate(questions, start=1):
            payload = {
                "question": question,
                "session_id": str(uuid.uuid4()),
                "install_id": headers["X-Install-Id"],
                "history": [],
            }
            try:
                resp = client.post(f"{base}/agent", headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"Q{index} FAILED: {exc}")
                rows.append(
                    {
                        "question": question[:60],
                        "error": str(exc),
                        "total_ms": 0.0,
                        "search_calls": 0,
                        "timings": {},
                    }
                )
                continue

            timings = data.get("timings_ms") or {}
            if isinstance(timings, dict):
                span_names.update(timings.keys())
            total_ms = float(timings.get("agent_total") or 0.0)
            search_calls = int(data.get("search_call_count") or 0)
            rows.append(
                {
                    "question": question[:60],
                    "total_ms": total_ms,
                    "search_calls": search_calls,
                    "timings": timings if isinstance(timings, dict) else {},
                }
            )
            print(f"Q{index} ok — {total_ms:.0f} ms, {search_calls} search(es)")

    priority_spans = [
        "agent_total",
        "gemini_llm",
        "google_search_agent",
        "search_zearn_doc_1",
        "search_zearn_doc_2",
        "search_zearn_doc_3",
        "retrieve_rerank",
        "retrieve_neighbors",
        "session_title",
        "db_persist",
    ]
    columns = ["question", "total_ms", "search_calls"] + [
        name for name in priority_spans if name in span_names
    ]
    widths = [max(len(col), 12 if col == "question" else 10) for col in columns]

    print("\n" + _format_row(columns, widths))
    print(_format_row(["-" * w for w in widths], widths))

    for row in rows:
        if row.get("error"):
            print(f"{row['question']} — ERROR: {row['error']}")
            continue
        timings = row.get("timings") or {}
        cells = [
            str(row["question"]),
            f"{float(row['total_ms']):.0f}",
            str(row["search_calls"]),
        ]
        for name in columns[3:]:
            cells.append(f"{float(timings.get(name, 0.0)):.0f}")
        print(_format_row(cells, widths))

    ok_rows = [r for r in rows if not r.get("error")]
    if ok_rows:
        avg_total = sum(float(r["total_ms"]) for r in ok_rows) / len(ok_rows)
        avg_search = sum(int(r["search_calls"]) for r in ok_rows) / len(ok_rows)
        print(f"\nAverage agent_total: {avg_total:.0f} ms")
        print(f"Average search_call_count: {avg_search:.1f}")

    return 0 if ok_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())

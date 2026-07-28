"""Golden-set evaluation — retrieval hit, faithfulness, and correctness.

Mirrors the RAGAS workflow from rag_vector_databases_live_session.ipynb.

Usage (local pipeline — same Pinecone index as Render when .env matches):
  python eval_golden.py
  python eval_golden.py --skip-northwind-upsert

Usage (live Render API — retrieval + /ask on the deployed service):
  python eval_golden.py --api-url https://ai-internship-i3lw.onrender.com --skip-northwind-upsert
  export RAG_API_URL=https://ai-internship-i3lw.onrender.com
  python eval_golden.py --skip-northwind-upsert

The FastAPI service also exposes POST /eval (same logic, runs on the server).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
import warnings
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# RAGAS still imports a removed LangChain VertexAI module — same shim as the notebook.
warnings.filterwarnings("ignore", category=DeprecationWarning)
_stub = types.ModuleType("langchain_community.chat_models.vertexai")
_stub.ChatVertexAI = type("ChatVertexAI", (), {})
sys.modules.setdefault("langchain_community.chat_models.vertexai", _stub)

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import EvaluationDataset, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import answer_correctness, faithfulness

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_GOLDEN_SET = THIS_DIR / "golden_set.json"
DEFAULT_API_URL = os.getenv("RAG_API_URL", "").strip()

NORTHWIND_SAMPLE = (
    "Northwind Robotics Employee Handbook\n"
    "Author: People Operations Team\n"
    "Document ID: POL-101\n\n"
    "Working hours are 09:00 to 17:30, Monday to Friday.\n\n"
    "Remote work. Employees may work remotely up to three days per week.\n"
    "Fully remote arrangements require director approval and are reviewed\n"
    "every six months. Employees working remotely must be reachable on\n"
    "Slack during core hours, which are 10:00 to 15:00.\n\n"
    "Annual leave is 28 days plus public holidays."
)


def load_golden_set(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Golden set must be a non-empty JSON array: {path}")
    return data


def retrieval_hit(retrieved_document_ids: list[str], expected_document_ids: list[str]) -> bool:
    retrieved = {doc_id.strip().lower() for doc_id in retrieved_document_ids}
    expected = {doc_id.strip().lower() for doc_id in expected_document_ids}
    return bool(retrieved & expected)


def ensure_northwind_indexed_local() -> None:
    from ingest import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, ingest_text

    ingest_text(
        document_id="employee_handbook",
        text=NORTHWIND_SAMPLE,
        source="northwind/employee_handbook.txt",
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    )


def ensure_northwind_indexed_api(api_url: str) -> None:
    payload = {"document_id": "employee_handbook", "text": NORTHWIND_SAMPLE}
    response = httpx.post(f"{api_url.rstrip('/')}/ingest", json=payload, timeout=120.0)
    response.raise_for_status()


def collect_eval_rows_local(golden_set: list[dict], *, verbose: bool = False) -> list[dict]:
    from main import DEFAULT_MODEL, build_grounding_prompt, call_model_structured, retrieve_context

    rows: list[dict] = []
    for item in golden_set:
        question = item["question"]
        reference = item["reference"]
        expected_docs = item.get("expected_document_ids", [])

        chunks, context, chunk_ids, _sources = retrieve_context(question)
        retrieved_doc_ids = [chunk.title for chunk in chunks if chunk.title]
        hit = retrieval_hit(retrieved_doc_ids, expected_docs)

        prompt = build_grounding_prompt(question, context)
        answer, _tokens, _prompt_tokens, _completion_tokens = call_model_structured(
            prompt, DEFAULT_MODEL
        )

        rows.append(_build_row(
            question, reference, expected_docs, retrieved_doc_ids, chunk_ids,
            hit, [chunk.text for chunk in chunks], answer.answer, answer.sources_needed,
        ))
        if verbose:
            _print_row_status(question, expected_docs, retrieved_doc_ids, answer.answer, hit)

    return rows


def collect_eval_rows_api(
    api_url: str,
    golden_set: list[dict],
    *,
    verbose: bool = False,
) -> list[dict]:
    base = api_url.rstrip("/")
    rows: list[dict] = []

    health = httpx.get(f"{base}/health", timeout=30.0)
    health.raise_for_status()

    for item in golden_set:
        question = item["question"]
        reference = item["reference"]
        expected_docs = item.get("expected_document_ids", [])

        retrieve_resp = httpx.post(
            f"{base}/retrieve",
            json={"question": question},
            timeout=120.0,
        )
        retrieve_resp.raise_for_status()
        chunks = retrieve_resp.json().get("chunks", [])

        ask_resp = httpx.post(
            f"{base}/ask",
            json={"question": question},
            timeout=120.0,
        )
        ask_resp.raise_for_status()
        ask_data = ask_resp.json()

        retrieved_doc_ids = [chunk["document_id"] for chunk in chunks if chunk.get("document_id")]
        chunk_ids = [chunk["chunk_id"] for chunk in chunks if chunk.get("chunk_id")]
        contexts = [chunk["text"] for chunk in chunks if chunk.get("text")]
        answer_obj = ask_data.get("answer", {})
        answer_text = answer_obj.get("answer", "")
        sources_needed = bool(answer_obj.get("sources_needed", False))
        hit = retrieval_hit(retrieved_doc_ids, expected_docs)

        rows.append(_build_row(
            question, reference, expected_docs, retrieved_doc_ids, chunk_ids,
            hit, contexts, answer_text, sources_needed,
        ))
        if verbose:
            _print_row_status(question, expected_docs, retrieved_doc_ids, answer_text, hit)

    return rows


def _build_row(
    question: str,
    reference: str,
    expected_docs: list[str],
    retrieved_doc_ids: list[str],
    chunk_ids: list[str],
    hit: bool,
    contexts: list[str],
    answer_text: str,
    sources_needed: bool,
) -> dict:
    return {
        "question": question,
        "reference": reference,
        "expected_document_ids": expected_docs,
        "retrieved_document_ids": retrieved_doc_ids,
        "chunk_ids": chunk_ids,
        "retrieval_hit": hit,
        "user_input": question,
        "retrieved_contexts": contexts,
        "response": answer_text,
        "sources_needed": sources_needed,
    }


def _print_row_status(
    question: str,
    expected_docs: list[str],
    retrieved_doc_ids: list[str],
    answer_text: str,
    hit: bool,
) -> None:
    status = "HIT" if hit else "MISS"
    print(f"[{status}] {question}")
    print(f"       expected: {expected_docs}")
    print(f"       retrieved: {retrieved_doc_ids}")
    preview = answer_text[:160] + ("..." if len(answer_text) > 160 else "")
    print(f"       answer: {preview}\n")


def score_with_ragas(eval_rows: list[dict]) -> pd.DataFrame:
    ragas_rows = [
        {
            "user_input": row["user_input"],
            "retrieved_contexts": row["retrieved_contexts"],
            "response": row["response"],
            "reference": row["reference"],
        }
        for row in eval_rows
    ]

    dataset = EvaluationDataset.from_list(ragas_rows)
    judge_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini", temperature=0))
    judge_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))

    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_correctness],
        llm=judge_llm,
        embeddings=judge_embeddings,
    )
    df = result.to_pandas().copy()

    # RAGAS can return NaN for individual rows on Render (timeouts / rate limits).
    # Retry missing scores one row at a time before giving up.
    for index in range(len(eval_rows)):
        missing_metrics: list = []
        if "faithfulness" in df.columns and _safe_float(df.iloc[index]["faithfulness"]) is None:
            missing_metrics.append(faithfulness)
        if (
            "answer_correctness" in df.columns
            and _safe_float(df.iloc[index]["answer_correctness"]) is None
        ):
            missing_metrics.append(answer_correctness)
        if not missing_metrics:
            continue

        retry_result = evaluate(
            dataset=EvaluationDataset.from_list([ragas_rows[index]]),
            metrics=missing_metrics,
            llm=judge_llm,
            embeddings=judge_embeddings,
        )
        retry_df = retry_result.to_pandas()
        for metric in missing_metrics:
            column = metric.name
            if column in retry_df.columns and column in df.columns:
                df.at[index, column] = retry_df.iloc[0][column]

    return df


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def build_eval_result(
    eval_rows: list[dict],
    scores_df: pd.DataFrame,
    *,
    golden_set_path: Path,
    api_url: str | None = None,
) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []

    for index, row in enumerate(eval_rows):
        faithfulness_score = (
            _safe_float(scores_df.iloc[index]["faithfulness"])
            if "faithfulness" in scores_df.columns
            else None
        )
        correctness = (
            _safe_float(scores_df.iloc[index]["answer_correctness"])
            if "answer_correctness" in scores_df.columns
            else None
        )
        questions.append({
            "question": row["question"],
            "reference": row["reference"],
            "expected_document_ids": row["expected_document_ids"],
            "retrieved_document_ids": row["retrieved_document_ids"],
            "retrieval_hit": row["retrieval_hit"],
            "faithfulness": faithfulness_score,
            "answer_correctness": correctness,
            "answer": row["response"],
            "sources_needed": row["sources_needed"],
        })

    retrieval_hits = sum(1 for row in eval_rows if row["retrieval_hit"])
    question_count = len(eval_rows)
    avg_faithfulness = (
        scores_df["faithfulness"].mean() if "faithfulness" in scores_df.columns else float("nan")
    )
    avg_correctness = (
        scores_df["answer_correctness"].mean()
        if "answer_correctness" in scores_df.columns
        else float("nan")
    )

    return {
        "golden_set": golden_set_path.name,
        "mode": "api" if api_url else "local",
        "api_url": api_url,
        "question_count": question_count,
        "averages": {
            "retrieval_hit": retrieval_hits / question_count if question_count else 0.0,
            "faithfulness": _safe_float(avg_faithfulness),
            "answer_correctness": _safe_float(avg_correctness),
            "retrieval_hits": retrieval_hits,
            "question_count": question_count,
        },
        "questions": questions,
    }


def run_eval(
    golden_set_path: Path = DEFAULT_GOLDEN_SET,
    *,
    api_url: str | None = None,
    skip_northwind_upsert: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run golden-set eval and return structured results for CLI, API, or Streamlit."""

    golden_set = load_golden_set(golden_set_path)
    normalized_api_url = api_url.rstrip("/") if api_url else None

    if not skip_northwind_upsert:
        if normalized_api_url:
            ensure_northwind_indexed_api(normalized_api_url)
        else:
            ensure_northwind_indexed_local()

    if normalized_api_url:
        eval_rows = collect_eval_rows_api(normalized_api_url, golden_set, verbose=verbose)
    else:
        eval_rows = collect_eval_rows_local(golden_set, verbose=verbose)

    ragas_result = score_with_ragas(eval_rows)
    return build_eval_result(
        eval_rows,
        ragas_result,
        golden_set_path=golden_set_path,
        api_url=normalized_api_url,
    )


def print_summary_from_result(result: dict[str, Any], api_url: str | None = None) -> None:
    if api_url:
        print(f"Evaluated via API: {api_url.rstrip('/')}\n")

    print("=" * 72)
    print("Per-question scores")
    print("=" * 72)
    for item in result["questions"]:
        hit_label = "HIT" if item["retrieval_hit"] else "MISS"
        faith = item["faithfulness"]
        correctness = item["answer_correctness"]
        faith_str = f"{faith:.4f}" if faith is not None else "—"
        corr_str = f"{correctness:.4f}" if correctness is not None else "—"
        print(f"[{hit_label}] {item['question']}")
        print(f"       faithfulness={faith_str}  answer_correctness={corr_str}")
        print(f"       expected: {item['expected_document_ids']}")
        print(f"       retrieved: {item['retrieved_document_ids']}\n")

    averages = result["averages"]
    print("=" * 72)
    print("Averages across golden set")
    print("=" * 72)
    print(
        f"  retrieval_hit:      {averages['retrieval_hit']:.2%} "
        f"({averages['retrieval_hits']}/{averages['question_count']})"
    )
    faith_avg = averages["faithfulness"]
    corr_avg = averages["answer_correctness"]
    if faith_avg is not None:
        print(f"  faithfulness:       {faith_avg:.4f}")
    else:
        print("  faithfulness:       —")
    if corr_avg is not None:
        print(f"  answer_correctness: {corr_avg:.4f}")
    else:
        print("  answer_correctness: —")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run golden-set RAG evaluation.")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=DEFAULT_GOLDEN_SET,
        help="Path to golden_set.json",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL or None,
        help="Live FastAPI base URL (e.g. https://your-app.onrender.com). Uses RAG_API_URL if unset.",
    )
    parser.add_argument(
        "--skip-northwind-upsert",
        action="store_true",
        help="Do not upsert the Northwind handbook before eval",
    )
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/") if args.api_url else None
    mode = f"API ({api_url})" if api_url else "local pipeline"
    print(f"Golden set: {len(load_golden_set(args.golden_set))} questions from {args.golden_set.name}")
    print(f"Mode: {mode}\n")

    if not args.skip_northwind_upsert:
        print("Ensuring employee_handbook is indexed for Northwind questions...\n")

    try:
        print("Scoring with RAGAS (faithfulness + answer_correctness)...")
        result = run_eval(
            args.golden_set,
            api_url=api_url,
            skip_northwind_upsert=args.skip_northwind_upsert,
            verbose=True,
        )
        print_summary_from_result(result, api_url=api_url)
    except httpx.HTTPStatusError as exc:
        print(f"API error: {exc.response.status_code} {exc.response.text[:500]}")
        if api_url and exc.response.status_code == 404:
            print("\nTip: deploy the latest code to Render — POST /retrieve is required for --api-url eval.")
        sys.exit(1)
    except KeyError as exc:
        print(f"Missing environment variable: {exc.args[0]}")
        sys.exit(1)
    except Exception as exc:
        print(f"Evaluation failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Golden-set evaluation — retrieval hit, faithfulness, and correctness.

Mirrors the RAGAS workflow from rag_vector_databases_live_session.ipynb.
Evaluates against the ingested Zearn corpus in Pinecone (run POST /ingest first).

Usage (local pipeline — same Pinecone index as Render when .env matches):
  python eval_golden.py

Usage (live Render API — retrieval + /ask on the deployed service):
  python eval_golden.py --api-url https://ai-internship-i3lw.onrender.com
  export RAG_API_URL=https://ai-internship-i3lw.onrender.com
  python eval_golden.py

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

from eval_format import format_eval_report_markdown


def load_golden_set(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Golden set must be a non-empty JSON array: {path}")
    return data


def retrieval_hit(retrieved_document_ids: list[str], expected_document_ids: list[str]) -> bool:
    retrieved = {doc_id.strip().lower() for doc_id in retrieved_document_ids}
    expected = {doc_id.strip().lower() for doc_id in expected_document_ids}
    return bool(retrieved & expected)


def collect_eval_rows_local(golden_set: list[dict], *, verbose: bool = False) -> list[dict]:
    from model_config import answer_model
    from main import generate_grounded_answer, retrieve_context

    rows: list[dict] = []
    for item in golden_set:
        question = item["question"]
        reference = item["reference"]
        expected_docs = item.get("expected_document_ids", [])

        # Retrieve over the open corpus (production /ask behavior, respecting
        # EXCLUDE_DOCUMENT_IDS) so retrieval_hit measures the retriever, not an
        # oracle document filter. expected_docs is used only to score the hit.
        chunks, context, chunk_ids, _sources = retrieve_context(question)
        retrieved_doc_ids = [chunk.document_id for chunk in chunks if chunk.document_id]
        hit = retrieval_hit(retrieved_doc_ids, expected_docs)

        answer, _tokens, _answer_pt, _answer_ct, _route, _ext_pt, _ext_ct = generate_grounded_answer(
            question, context, answer_model()
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
        # Open-corpus retrieval (see collect_eval_rows_local); expected_docs
        # only scores the hit, it does not filter retrieval.
        request_payload: dict = {"question": question}

        retrieve_resp = httpx.post(
            f"{base}/retrieve",
            json=request_payload,
            timeout=120.0,
        )
        retrieve_resp.raise_for_status()
        chunks = retrieve_resp.json().get("chunks", [])

        ask_resp = httpx.post(
            f"{base}/ask",
            json=request_payload,
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
    preview = answer_text
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

    from model_config import embedding_model, ragas_judge_model

    dataset = EvaluationDataset.from_list(ragas_rows)
    judge_llm = LangchainLLMWrapper(
        ChatOpenAI(model=ragas_judge_model(), temperature=0)
    )
    judge_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=embedding_model()))

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


def get_eval_config() -> dict[str, Any]:
    """Retrieval/chunking settings used during golden-set eval."""

    from ingest import excluded_document_ids_from_env

    try:
        from retrieval_config import (
            chunk_overlap,
            chunk_size,
            max_chunks_per_document,
            max_context_chunks,
            max_context_chunks_enabled,
            neighbor_chunk_radius,
            neighbor_chunks_enabled,
            neighbor_merge_enabled,
            retrieval_fetch_k,
            retrieval_k,
        )
        from main import hybrid_search_enabled, two_step_generation_enabled
        from generation_config import (
            answer_verbosity,
            citations_enabled,
            prompt_conflict_resolution_enabled,
        )
        from model_config import (
            answer_model,
            embedding_model,
            extraction_model,
            generation_temperature,
            ragas_judge_model,
        )
        from question_classifier import question_routing_enabled
        from rerank import (
            context_order_by_rerank_score_enabled,
            relevance_filter_enabled,
            relevance_min_chunks,
            relevance_min_score_gap,
            rerank_candidates_count,
            rerank_enabled,
            rerank_model_name,
        )

        return {
            "chunk_size": chunk_size(),
            "chunk_overlap": chunk_overlap(),
            "k": retrieval_k(),
            "fetch_k": retrieval_fetch_k(),
            "max_per_document": max_chunks_per_document(),
            "hybrid_search": hybrid_search_enabled(),
            "rerank_enabled": rerank_enabled(),
            "rerank_candidates": rerank_candidates_count(),
            "rerank_model": rerank_model_name(),
            "neighbor_chunks_enabled": neighbor_chunks_enabled(),
            "neighbor_chunk_radius": neighbor_chunk_radius(),
            "neighbor_merge_enabled": neighbor_merge_enabled(),
            "max_context_chunks_enabled": max_context_chunks_enabled(),
            "max_context_chunks": max_context_chunks(),
            "exclude_document_ids": excluded_document_ids_from_env(),
            "two_step_generation": two_step_generation_enabled(),
            "question_routing_enabled": question_routing_enabled(),
            "answer_verbosity": answer_verbosity(),
            "citations_enabled": citations_enabled(),
            "relevance_filter_enabled": relevance_filter_enabled(),
            "relevance_min_score_gap": relevance_min_score_gap(),
            "relevance_min_chunks": relevance_min_chunks(),
            "prompt_conflict_resolution_enabled": prompt_conflict_resolution_enabled(),
            "context_order_by_rerank_score": context_order_by_rerank_score_enabled(),
            "answer_model": answer_model(),
            "extraction_model": extraction_model(),
            "embedding_model": embedding_model(),
            "ragas_judge_model": ragas_judge_model(),
            "generation_temperature": generation_temperature(),
        }
    except ImportError:
        return {
            "chunk_size": None,
            "chunk_overlap": None,
            "k": None,
            "fetch_k": None,
            "max_per_document": None,
            "hybrid_search": None,
            "rerank_enabled": None,
            "rerank_candidates": None,
            "rerank_model": None,
            "neighbor_chunks_enabled": None,
            "neighbor_chunk_radius": None,
            "neighbor_merge_enabled": None,
            "max_context_chunks_enabled": None,
            "max_context_chunks": None,
            "exclude_document_ids": excluded_document_ids_from_env(),
        }


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
            "chunk_ids": row.get("chunk_ids", []),
            "retrieved_contexts": row.get("retrieved_contexts", []),
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
        "config": get_eval_config(),
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
    verbose: bool = False,
) -> dict[str, Any]:
    """Run golden-set eval and return structured results for CLI, API, or Streamlit."""

    golden_set = load_golden_set(golden_set_path)
    normalized_api_url = api_url.rstrip("/") if api_url else None

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
    """Print the full eval report (all sections from eval_format, never truncated)."""
    if api_url:
        print(f"Evaluated via API: {api_url.rstrip('/')}\n")
    print(format_eval_report_markdown(result))
    print()


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
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/") if args.api_url else None
    mode = f"API ({api_url})" if api_url else "local pipeline"
    print(f"Golden set: {len(load_golden_set(args.golden_set))} questions from {args.golden_set.name}")
    print(f"Mode: {mode}\n")

    try:
        print("Scoring with RAGAS (faithfulness + answer_correctness)...")
        result = run_eval(
            args.golden_set,
            api_url=api_url,
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

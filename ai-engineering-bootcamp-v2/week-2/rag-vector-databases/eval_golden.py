"""Golden-set evaluation — retrieval hit, faithfulness, and correctness.

Mirrors the RAGAS workflow from rag_vector_databases_live_session.ipynb.

Usage (local pipeline — same Pinecone index as Render when .env matches):
  python eval_golden.py
  python eval_golden.py --skip-northwind-upsert

Usage (live Render API — retrieval + /ask on the deployed service):
  python eval_golden.py --api-url https://ai-internship-i3lw.onrender.com --skip-northwind-upsert
  export RAG_API_URL=https://ai-internship-i3lw.onrender.com
  python eval_golden.py --skip-northwind-upsert
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
import warnings
from pathlib import Path

import httpx
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


def collect_eval_rows_local(golden_set: list[dict]) -> list[dict]:
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
        _print_row_status(question, expected_docs, retrieved_doc_ids, answer.answer, hit)

    return rows


def collect_eval_rows_api(api_url: str, golden_set: list[dict]) -> list[dict]:
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


def score_with_ragas(eval_rows: list[dict]):
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

    return evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_correctness],
        llm=judge_llm,
        embeddings=judge_embeddings,
    )


def print_summary(eval_rows: list[dict], ragas_result, api_url: str | None = None) -> None:
    df = ragas_result.to_pandas()
    df["retrieval_hit"] = [row["retrieval_hit"] for row in eval_rows]
    df["expected_document_ids"] = [row["expected_document_ids"] for row in eval_rows]
    df["retrieved_document_ids"] = [row["retrieved_document_ids"] for row in eval_rows]

    if api_url:
        print(f"Evaluated via API: {api_url.rstrip('/')}\n")

    display_cols = [
        "user_input",
        "retrieval_hit",
        "faithfulness",
        "answer_correctness",
        "expected_document_ids",
        "retrieved_document_ids",
    ]
    present_cols = [col for col in display_cols if col in df.columns]

    print("=" * 72)
    print("Per-question scores")
    print("=" * 72)
    print(df[present_cols].to_string(index=False))

    retrieval_rate = sum(1 for row in eval_rows if row["retrieval_hit"]) / len(eval_rows)
    avg_faithfulness = df["faithfulness"].mean() if "faithfulness" in df.columns else float("nan")
    avg_correctness = (
        df["answer_correctness"].mean() if "answer_correctness" in df.columns else float("nan")
    )

    print("\n" + "=" * 72)
    print("Averages across golden set")
    print("=" * 72)
    print(f"  retrieval_hit:      {retrieval_rate:.2%} ({sum(row['retrieval_hit'] for row in eval_rows)}/{len(eval_rows)})")
    print(f"  faithfulness:       {avg_faithfulness:.4f}")
    print(f"  answer_correctness: {avg_correctness:.4f}")


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

    golden_set = load_golden_set(args.golden_set)
    api_url = args.api_url.rstrip("/") if args.api_url else None
    mode = f"API ({api_url})" if api_url else "local pipeline"
    print(f"Golden set: {len(golden_set)} questions from {args.golden_set.name}")
    print(f"Mode: {mode}\n")

    if not args.skip_northwind_upsert:
        print("Ensuring employee_handbook is indexed for Northwind questions...")
        if api_url:
            ensure_northwind_indexed_api(api_url)
        else:
            ensure_northwind_indexed_local()
        print()

    try:
        if api_url:
            eval_rows = collect_eval_rows_api(api_url, golden_set)
        else:
            eval_rows = collect_eval_rows_local(golden_set)

        print("Scoring with RAGAS locally (faithfulness + answer_correctness)...")
        ragas_result = score_with_ragas(eval_rows)
        print_summary(eval_rows, ragas_result, api_url=api_url)
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

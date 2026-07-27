"""Golden-set evaluation — retrieval hit, faithfulness, and correctness.

Mirrors the RAGAS workflow from rag_vector_databases_live_session.ipynb, but runs
against the Week 2 Pinecone pipeline (main.py + ingest.py).

Usage:
  cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
  source .venv/bin/activate
  pip install -r requirements-dev.txt
  python eval_golden.py
  python eval_golden.py --golden-set golden_set.json
"""

from __future__ import annotations

import argparse
import json
import sys
import types
import warnings
from pathlib import Path

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

from ingest import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, ingest_text
from main import (
    DEFAULT_MODEL,
    build_grounding_prompt,
    call_model_structured,
    retrieve_context,
)

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_GOLDEN_SET = THIS_DIR / "golden_set.json"

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


def ensure_northwind_indexed() -> None:
    """Upsert the handbook so Northwind questions can hit in eval."""
    ingest_text(
        document_id="employee_handbook",
        text=NORTHWIND_SAMPLE,
        source="northwind/employee_handbook.txt",
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    )


def retrieval_hit(retrieved_document_ids: list[str], expected_document_ids: list[str]) -> bool:
    retrieved = {doc_id.strip().lower() for doc_id in retrieved_document_ids}
    expected = {doc_id.strip().lower() for doc_id in expected_document_ids}
    return bool(retrieved & expected)


def collect_eval_rows(golden_set: list[dict]) -> list[dict]:
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

        rows.append(
            {
                "question": question,
                "reference": reference,
                "expected_document_ids": expected_docs,
                "retrieved_document_ids": retrieved_doc_ids,
                "chunk_ids": chunk_ids,
                "retrieval_hit": hit,
                "user_input": question,
                "retrieved_contexts": [chunk.text for chunk in chunks],
                "response": answer.answer,
                "sources_needed": answer.sources_needed,
            }
        )

        status = "HIT" if hit else "MISS"
        print(f"[{status}] {question}")
        print(f"       expected: {expected_docs}")
        print(f"       retrieved: {retrieved_doc_ids}")
        print(f"       answer: {answer.answer[:160]}{'...' if len(answer.answer) > 160 else ''}\n")

    return rows


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


def print_summary(eval_rows: list[dict], ragas_result) -> None:
    df = ragas_result.to_pandas()
    df["retrieval_hit"] = [row["retrieval_hit"] for row in eval_rows]
    df["expected_document_ids"] = [row["expected_document_ids"] for row in eval_rows]
    df["retrieved_document_ids"] = [row["retrieved_document_ids"] for row in eval_rows]

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
        "--skip-northwind-upsert",
        action="store_true",
        help="Do not upsert the Northwind handbook before eval",
    )
    args = parser.parse_args()

    golden_set = load_golden_set(args.golden_set)
    print(f"Golden set: {len(golden_set)} questions from {args.golden_set.name}\n")

    if not args.skip_northwind_upsert:
        print("Ensuring employee_handbook is indexed for Northwind questions...")
        ensure_northwind_indexed()
        print()

    try:
        eval_rows = collect_eval_rows(golden_set)
        print("Scoring with RAGAS (faithfulness + answer_correctness)...")
        ragas_result = score_with_ragas(eval_rows)
        print_summary(eval_rows, ragas_result)
    except KeyError as exc:
        print(f"Missing environment variable: {exc.args[0]}")
        sys.exit(1)
    except Exception as exc:
        print(f"Evaluation failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

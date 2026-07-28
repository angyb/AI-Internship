"""Debug retrieval without calling the LLM.

Shows dense, BM25, and hybrid (RRF) rankings side-by-side.

Usage:
  python debug_retrieve.py "director approval fully remote"
  python debug_retrieve.py --dense-only "How do I add students to my class?"
  python debug_retrieve.py   # uses a default sample question
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from ingest import debug_retrieve, debug_retrieve_hybrid

DEFAULT_QUESTION = "How do I add students to my class?"
PREVIEW_CHARS = 300


def print_debug_chunks(title: str, chunks) -> None:
    print(f"=== {title} ===")
    if not chunks:
        print("(no results)\n")
        return

    for chunk in chunks:
        preview = chunk.text[:PREVIEW_CHARS]
        if len(chunk.text) > PREVIEW_CHARS:
            preview += "..."

        print(f"--- #{chunk.rank} score={chunk.score:.4f} ---")
        print(f"chunk_id: {chunk.chunk_id}")
        print(f"document_id: {chunk.document_id}")
        print(f"chunk_index: {chunk.chunk_index}")
        print(f"source: {chunk.source}")
        print(preview)
        print()


def main() -> None:
    args = sys.argv[1:]
    dense_only = False
    if args and args[0] == "--dense-only":
        dense_only = True
        args = args[1:]

    question = " ".join(args).strip() or DEFAULT_QUESTION
    print(f"Question: {question}\n")

    try:
        if dense_only:
            chunks = debug_retrieve(question, k=5)
            if not chunks:
                print("No chunks returned. Run POST /ingest first to populate Pinecone.")
                sys.exit(0)
            print_debug_chunks("Dense (Pinecone only)", chunks)
            return

        result = debug_retrieve_hybrid(question, k=5)
    except KeyError as exc:
        print(f"Missing environment variable: {exc.args[0]}")
        sys.exit(1)
    except Exception as exc:
        print(f"Retrieve failed: {exc}")
        sys.exit(1)

    if not result.dense and not result.bm25 and not result.fused:
        print("No chunks returned. Run POST /ingest first to populate Pinecone.")
        sys.exit(0)

    print_debug_chunks("Dense (Pinecone)", result.dense)
    print_debug_chunks("BM25 (keyword)", result.bm25)
    print_debug_chunks("Hybrid (RRF fused)", result.fused)


if __name__ == "__main__":
    main()

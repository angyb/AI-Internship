"""Debug retrieval without calling the LLM.

Shows raw Pinecone chunks only — not a synthesized answer. To test the full
RAG pipeline (retrieve + generate), use POST /ask or curl against the API.

Usage:
  python debug_retrieve.py "How do I add students to my class?"
  python debug_retrieve.py   # uses a default sample question
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from ingest import debug_retrieve

DEFAULT_QUESTION = "How do I add students to my class?"
PREVIEW_CHARS = 300


def main() -> None:
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION
    print(f"Question: {question}\n")

    try:
        chunks = debug_retrieve(question, k=5)
    except KeyError as exc:
        print(f"Missing environment variable: {exc.args[0]}")
        sys.exit(1)
    except Exception as exc:
        print(f"Retrieve failed: {exc}")
        sys.exit(1)

    if not chunks:
        print("No chunks returned. Run POST /ingest first to populate Pinecone.")
        sys.exit(0)

    for i, chunk in enumerate(chunks, start=1):
        preview = chunk.text[:PREVIEW_CHARS]
        if len(chunk.text) > PREVIEW_CHARS:
            preview += "..."

        print(f"--- #{i} score={chunk.score:.4f} ---")
        print(f"document_id: {chunk.document_id}")
        print(f"chunk_index: {chunk.chunk_index}")
        print(f"source: {chunk.source}")
        print(preview)
        print()


if __name__ == "__main__":
    main()

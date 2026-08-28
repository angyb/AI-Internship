"""Ingest documents/data/zearn_lessons.csv — one Pinecone document per grade + mission.

Usage:
  cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
  source .venv/bin/activate
  python ingest_zearn_lessons.py
  python ingest_zearn_lessons.py --path ../documents/data/zearn_lessons.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from ingest import ZEARN_LESSONS_CSV, ingest_zearn_lessons_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest zearn_lessons.csv into Pinecone (one document_id per grade + mission)."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=ZEARN_LESSONS_CSV,
        help="Path to zearn_lessons.csv",
    )
    args = parser.parse_args()

    try:
        results = ingest_zearn_lessons_csv(args.path)
    except KeyError as exc:
        print(f"Missing environment variable: {exc.args[0]}")
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"Ingest failed: {exc}")
        sys.exit(1)

    total_chunks = sum(r.chunks_indexed for r in results)
    print(f"Missions ingested: {len(results)}")
    print(f"Total chunks indexed: {total_chunks}")
    for result in results:
        print(f"  {result.document_id}: {result.chunks_indexed} chunks")


if __name__ == "__main__":
    main()

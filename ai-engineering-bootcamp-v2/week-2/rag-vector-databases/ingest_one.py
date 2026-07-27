"""Ingest a single file into Pinecone without clearing the rest of the index.

Usage:
  python ingest_one.py ../documents/northwind/employee_handbook.txt
  python ingest_one.py ../documents/northwind/employee_handbook.txt --document-id employee_handbook
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from ingest import ingest_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one document file into Pinecone.")
    parser.add_argument("path", help="Path to a .txt (or other text) file")
    parser.add_argument(
        "--document-id",
        help="document_id stored in Pinecone (default: file stem)",
    )
    args = parser.parse_args()

    try:
        result = ingest_file(args.path, document_id=args.document_id)
    except KeyError as exc:
        print(f"Missing environment variable: {exc.args[0]}")
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"Ingest failed: {exc}")
        sys.exit(1)

    print(f"document_id: {result.document_id}")
    print(f"chunks_indexed: {result.chunks_indexed}")
    print(f"status: {result.status}")


if __name__ == "__main__":
    main()

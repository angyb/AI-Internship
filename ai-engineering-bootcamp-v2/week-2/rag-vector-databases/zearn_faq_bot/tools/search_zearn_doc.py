"""search_zearn_doc — RAG retrieval tool backed by in-process retrieve_context()."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from zearn_faq_bot.constants import CHUNK_TEXT_LIMIT

DOCS_DIR = Path(__file__).resolve().parents[3] / "documents"


@lru_cache(maxsize=512)
def _doc_meta_from_source(source: str) -> tuple[str, str]:
    """Return (title, source_url) from local docs when Pinecone metadata is sparse."""
    if not source:
        return "", ""

    path = DOCS_DIR / source
    if not path.is_file():
        return "", ""

    if path.suffix.lower() == ".md":
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return "", ""
        if not raw.startswith("---"):
            return "", ""
        parts = raw.split("---", 2)
        if len(parts) < 3:
            return "", ""
        title = ""
        source_url = ""
        for line in parts[1].strip().splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key == "title":
                title = value
            elif key == "source_url":
                source_url = value
        return title, source_url

    if path.suffix.lower() == ".pdf":
        manifest_path = path.parent / "manifest.json"
        if not manifest_path.is_file():
            return "", ""
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "", ""
        if not isinstance(entries, list):
            return "", ""
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("filename", "")).strip() == path.name:
                return "", str(entry.get("url", "")).strip()
        return "", ""

    return "", ""


def _format_chunks_from_retrieved(chunks: list[Any]) -> dict:
    """Turn RetrievedChunk objects into the search_zearn_doc tool response shape."""
    out = []
    for chunk in chunks:
        text = chunk.text
        if len(text) > CHUNK_TEXT_LIMIT:
            text = text[:CHUNK_TEXT_LIMIT] + "..."

        title = (getattr(chunk, "title", "") or "").strip()
        source_url = (getattr(chunk, "source_url", "") or "").strip()
        source = chunk.source or ""
        document_id = chunk.document_id or ""

        # Older Pinecone vectors often omit title/source_url — fill from local docs.
        if not source_url or not title or title == document_id:
            fm_title, fm_url = _doc_meta_from_source(source)
            if not source_url and fm_url:
                source_url = fm_url
            if fm_title and (not title or title == document_id):
                title = fm_title
        if not title:
            title = document_id

        out.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": document_id,
                "title": title,
                "text": text,
                "source": source,
                "source_url": source_url,
            }
        )
    return {"chunk_count": len(out), "chunks": out}


def search_zearn_doc(question: str) -> dict:
    """Search the Zearn knowledge base for relevant documentation chunks.

    Use this tool before answering factual questions about Zearn Math,
    teacher and admin workflows, Tower Alerts, rosters, accounts, or product features.

    Args:
        question: A search query describing what you need from the docs.

    Returns:
        Dict with chunk_count and chunks (chunk_id, document_id, title,
        text, source, source_url). Use title + source_url for citations.
    """
    try:
        # Lazy import avoids circular dependency with main.py → zearn_support_agent.
        from main import retrieve_context

        chunks, _context, _chunk_ids, _sources = retrieve_context(question)
    except KeyError as exc:
        return {
            "error": f"Missing required environment variable: {exc.args[0]}",
            "chunks": [],
            "chunk_count": 0,
        }
    except Exception as exc:
        return {
            "error": f"Retrieval failed: {exc}",
            "chunks": [],
            "chunk_count": 0,
        }

    if not chunks:
        return {"chunk_count": 0, "chunks": []}

    return _format_chunks_from_retrieved(chunks)

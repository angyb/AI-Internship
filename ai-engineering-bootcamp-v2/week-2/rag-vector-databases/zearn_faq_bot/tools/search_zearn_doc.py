"""search_zearn_doc — RAG retrieval tool backed by in-process retrieve_context()."""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

from zearn_faq_bot.constants import CHUNK_TEXT_LIMIT, MAX_SEARCH_ZEARN_DOC_CALLS
from secret_redaction import safe_error_message

DOCS_DIR = Path(__file__).resolve().parents[3] / "documents"
_search_call_count: ContextVar[int] = ContextVar("search_zearn_doc_call_count", default=0)
_role_search_phrase: ContextVar[str | None] = ContextVar(
    "memory_role_search_phrase", default=None
)

_ROLE_QUERY_NOISE = re.compile(
    r"\b("
    r"teachers?|administrators?|admins?|parents?|students?|"
    r"school\s+districts?|school\s+admins?|group\s+admins?"
    r")\b",
    re.IGNORECASE,
)


def reset_search_call_count() -> None:
    """Reset per-question search_zearn_doc call count (called at start of each agent run)."""
    _search_call_count.set(0)
    _role_search_phrase.set(None)


def set_role_search_phrase(phrase: str | None) -> None:
    """Set the role phrase enforced on search_zearn_doc queries for this agent run."""
    _role_search_phrase.set(phrase)


def scope_search_query(question: str, role_phrase: str | None) -> str:
    """Strip cross-role terms and append the single allowed role phrase."""
    text = (question or "").strip()
    if not role_phrase:
        return text
    cleaned = _ROLE_QUERY_NOISE.sub(" ", text)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = text
    if role_phrase.lower() in cleaned.lower():
        return cleaned
    return f"{cleaned} {role_phrase}".strip()


def get_search_call_count() -> int:
    """Return how many search_zearn_doc calls ran in the current agent request."""
    return _search_call_count.get()


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
    call_count = _search_call_count.get()
    if call_count >= MAX_SEARCH_ZEARN_DOC_CALLS:
        return {
            "error": (
                f"search_zearn_doc call limit ({MAX_SEARCH_ZEARN_DOC_CALLS}) "
                "reached for this question. Answer from prior results, use "
                "google_search_agent, or refuse."
            ),
            "chunks": [],
            "chunk_count": 0,
        }
    _search_call_count.set(call_count + 1)
    span_name = f"search_zearn_doc_{call_count + 1}"
    role_phrase = _role_search_phrase.get()
    query_used = scope_search_query(question, role_phrase)

    try:
        from agent_retrieval import retrieval_lite_enabled
        from main import retrieve_context
        from timing import timed_span

        lite = retrieval_lite_enabled()
        with timed_span(span_name):
            chunks, _context, _chunk_ids, _sources = retrieve_context(query_used, lite=lite)
    except KeyError as exc:
        return {
            "error": f"Missing required environment variable: {exc.args[0]}",
            "chunks": [],
            "chunk_count": 0,
        }
    except Exception as exc:
        return {
            "error": safe_error_message(exc, prefix="Retrieval failed"),
            "chunks": [],
            "chunk_count": 0,
        }

    if not chunks:
        payload: dict = {"chunk_count": 0, "chunks": []}
        if query_used != question.strip():
            payload["query_used"] = query_used
        return payload

    result = _format_chunks_from_retrieved(chunks)
    if query_used != question.strip():
        result["query_used"] = query_used
    return result

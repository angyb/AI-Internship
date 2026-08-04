"""search_zearn_doc — RAG retrieval tool backed by in-process retrieve_context()."""

from __future__ import annotations

from typing import Any

from zearn_faq_bot.constants import CHUNK_TEXT_LIMIT


def _format_chunks_from_retrieved(chunks: list[Any]) -> dict:
    """Turn RetrievedChunk objects into the search_zearn_doc tool response shape."""
    out = []
    for chunk in chunks:
        text = chunk.text
        if len(text) > CHUNK_TEXT_LIMIT:
            text = text[:CHUNK_TEXT_LIMIT] + "..."
        out.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "text": text,
                "source": chunk.source,
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
        Dict with chunk_count and chunks (chunk_id, document_id, text, source).
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

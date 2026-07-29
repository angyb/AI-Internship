"""Local cross-encoder reranking — no paid API (sentence-transformers on CPU)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ingest import RetrievedChunk

logger = logging.getLogger(__name__)

DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_cross_encoder = None


def rerank_enabled() -> bool:
    return os.getenv("RERANK_ENABLED", "true").lower() != "false"


def rerank_model_name() -> str:
    return os.getenv("RERANK_MODEL", DEFAULT_RERANK_MODEL).strip() or DEFAULT_RERANK_MODEL


def rerank_candidates_count() -> int:
    raw = os.getenv("RERANK_CANDIDATES", "20").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 20


def rerank_candidate_max_per_document() -> int:
    raw = os.getenv("RERANK_CANDIDATE_MAX_PER_DOC", "5").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 5


def get_cross_encoder():
    """Lazy-load the cross-encoder (downloads model weights on first use)."""
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder

        model_name = rerank_model_name()
        logger.info("Loading cross-encoder reranker: %s", model_name)
        _cross_encoder = CrossEncoder(model_name)
    return _cross_encoder


def warmup_reranker() -> None:
    """Load the reranker at startup so the first /ask is not slow."""
    if not rerank_enabled():
        return
    get_cross_encoder()


def rerank_chunks(question: str, chunks: list[RetrievedChunk], top_k: int | None = None) -> list[RetrievedChunk]:
    """Score (query, chunk) pairs and return chunks sorted by relevance."""
    if not chunks:
        return []

    limit = top_k if top_k is not None else len(chunks)
    if len(chunks) == 1:
        return chunks[:limit]

    model = get_cross_encoder()
    pairs = [(question, chunk.text) for chunk in chunks]
    scores = model.predict(pairs)

    ranked = sorted(zip(chunks, scores, strict=True), key=lambda item: float(item[1]), reverse=True)
    return [chunk for chunk, _score in ranked[:limit]]

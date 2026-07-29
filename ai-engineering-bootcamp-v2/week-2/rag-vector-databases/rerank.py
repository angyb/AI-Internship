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
    raw = os.getenv("RERANK_CANDIDATES", "30").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 30


def rerank_candidate_max_per_document() -> int:
    raw = os.getenv("RERANK_CANDIDATE_MAX_PER_DOC", "5").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 5


def relevance_filter_enabled() -> bool:
    """Drop low-scoring context blocks before generation (uses cross-encoder)."""
    return os.getenv("RELEVANCE_FILTER_ENABLED", "true").lower() != "false"


def relevance_min_score_gap() -> float:
    """Max allowed drop from the best chunk score; blocks below best - gap are removed."""
    raw = os.getenv("RELEVANCE_MIN_SCORE_GAP", "1.0").strip()
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return 1.0


def relevance_min_chunks() -> int:
    """Always keep at least this many context blocks after filtering."""
    raw = os.getenv("RELEVANCE_MIN_CHUNKS", "1").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 1


def context_order_by_rerank_score_enabled() -> bool:
    """Sort final LLM context blocks by cross-encoder score (best first)."""
    return os.getenv("CONTEXT_ORDER_BY_RERANK_SCORE", "true").lower() != "false"


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
    scored = score_chunks(question, chunks)
    if not scored:
        return []

    limit = top_k if top_k is not None else len(scored)
    return [chunk for chunk, _score in scored[:limit]]


def order_chunks_by_rerank_score(question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Reorder context blocks for the LLM prompt — highest cross-encoder score first."""
    if not chunks or not context_order_by_rerank_score_enabled():
        return chunks
    scored = score_chunks(question, chunks)
    return [chunk for chunk, _score in scored]


def score_chunks(question: str, chunks: list[RetrievedChunk]) -> list[tuple[RetrievedChunk, float]]:
    """Return chunks with cross-encoder relevance scores, best first."""
    if not chunks:
        return []
    if len(chunks) == 1:
        model = get_cross_encoder()
        score = float(model.predict([(question, chunks[0].text)])[0])
        return [(chunks[0], score)]

    model = get_cross_encoder()
    pairs = [(question, chunk.text) for chunk in chunks]
    scores = model.predict(pairs)
    ranked = sorted(
        zip(chunks, [float(score) for score in scores], strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked


def filter_chunks_by_relevance(question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Drop context blocks too far below the best cross-encoder score (pre-generation)."""
    if not chunks or not relevance_filter_enabled():
        return chunks

    scored = score_chunks(question, chunks)
    best = scored[0][1]
    gap_limit = relevance_min_score_gap()
    min_keep = min(relevance_min_chunks(), len(scored))

    kept = [chunk for chunk, score in scored if (best - score) <= gap_limit]
    if len(kept) < min_keep:
        kept = [chunk for chunk, _score in scored[:min_keep]]

    if len(kept) < len(chunks):
        dropped = len(chunks) - len(kept)
        logger.info(
            "Relevance filter dropped %d/%d context block(s) (best=%.3f, gap<=%.3f)",
            dropped,
            len(chunks),
            best,
            gap_limit,
        )

    return kept

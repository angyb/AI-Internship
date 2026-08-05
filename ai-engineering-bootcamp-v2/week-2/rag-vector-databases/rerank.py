"""Local cross-encoder reranking — no paid API (sentence-transformers on CPU)."""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from env_utils import bool_env, float_env, int_env

if TYPE_CHECKING:
    from ingest import RetrievedChunk

logger = logging.getLogger(__name__)

DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_cross_encoder = None
_cross_encoder_lock = threading.Lock()


def rerank_enabled() -> bool:
    return bool_env("RERANK_ENABLED", True)


def rerank_model_name() -> str:
    return os.getenv("RERANK_MODEL", DEFAULT_RERANK_MODEL).strip() or DEFAULT_RERANK_MODEL


def rerank_candidates_count() -> int:
    return int_env("RERANK_CANDIDATES", 30, minimum=1)


def rerank_candidate_max_per_document() -> int:
    return int_env("RERANK_CANDIDATE_MAX_PER_DOC", 5, minimum=1)


def relevance_filter_enabled() -> bool:
    """Drop low-scoring context blocks before generation (uses cross-encoder)."""
    return bool_env("RELEVANCE_FILTER_ENABLED", True)


def relevance_min_score_gap() -> float:
    """Max allowed drop from the best chunk score; blocks below best - gap are removed."""
    return float_env("RELEVANCE_MIN_SCORE_GAP", 1.0, minimum=0.0)


def relevance_min_chunks() -> int:
    """Always keep at least this many context blocks after filtering."""
    return int_env("RELEVANCE_MIN_CHUNKS", 1, minimum=1)


def context_order_by_rerank_score_enabled() -> bool:
    """Sort final LLM context blocks by cross-encoder score (best first)."""
    return bool_env("CONTEXT_ORDER_BY_RERANK_SCORE", True)


def get_cross_encoder():
    """Lazy-load the cross-encoder (downloads model weights on first use)."""
    global _cross_encoder
    if _cross_encoder is None:
        with _cross_encoder_lock:
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


def filter_and_order_chunks_by_relevance(
    question: str, chunks: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    """Relevance filter + score ordering in a single cross-encoder pass.

    Equivalent to filter_chunks_by_relevance() followed by
    order_chunks_by_rerank_score(), but scores the chunks only once.
    """
    filter_on = relevance_filter_enabled()
    order_on = context_order_by_rerank_score_enabled()
    if not chunks or (not filter_on and not order_on):
        return chunks

    scored = score_chunks(question, chunks)  # best-first
    if not scored:
        return []

    if not filter_on:
        # Only ordering requested — scored is already best-first.
        return [chunk for chunk, _score in scored]

    best = scored[0][1]
    gap_limit = relevance_min_score_gap()
    min_keep = min(relevance_min_chunks(), len(scored))

    kept = [(chunk, score) for chunk, score in scored if (best - score) <= gap_limit]
    if len(kept) < min_keep:
        kept = scored[:min_keep]

    if len(kept) < len(chunks):
        logger.info(
            "Relevance filter dropped %d/%d context block(s) (best=%.3f, gap<=%.3f)",
            len(chunks) - len(kept),
            len(chunks),
            best,
            gap_limit,
        )

    # kept is already best-first, matching order_chunks_by_rerank_score output.
    return [chunk for chunk, _score in kept]

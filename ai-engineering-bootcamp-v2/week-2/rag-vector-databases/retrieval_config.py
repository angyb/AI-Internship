"""Environment-backed retrieval settings for /ask, /retrieve, and eval."""

from __future__ import annotations

from env_utils import bool_env, int_env as _int_env


def retrieval_k() -> int:
    """Final number of chunks passed to the LLM after filtering."""
    return _int_env("RETRIEVAL_K", 5)


def retrieval_fetch_k() -> int:
    """Candidate pool size when reranking is disabled."""
    return _int_env("RETRIEVAL_FETCH_K", 10)


def max_chunks_per_document() -> int:
    """Cap on chunks from the same document_id in the final context."""
    return _int_env("MAX_CHUNKS_PER_DOCUMENT", 2)


def neighbor_chunks_enabled() -> bool:
    return bool_env("NEIGHBOR_CHUNKS_ENABLED", True)


def neighbor_chunk_radius() -> int:
    """How many adjacent chunk_index steps to include on each side of a hit (0 = off)."""
    return _int_env("NEIGHBOR_CHUNK_RADIUS", 1, minimum=0)


def neighbor_merge_enabled() -> bool:
    """Merge each hit with its neighbors into one context block per (document_id, hit)."""
    return bool_env("NEIGHBOR_MERGE_ENABLED", True)


def max_context_chunks_enabled() -> bool:
    return bool_env("MAX_CONTEXT_CHUNKS_ENABLED", True)


def max_context_chunks() -> int:
    """Cap LLM context blocks after neighbor expansion/merge."""
    return _int_env("MAX_CONTEXT_CHUNKS", 5)


def chunk_size() -> int:
    """Character chunk size for ingest text splitting."""
    return _int_env("CHUNK_SIZE", 800, minimum=100)


def chunk_overlap() -> int:
    """Character overlap between consecutive chunks during ingest."""
    return _int_env("CHUNK_OVERLAP", 100, minimum=0)

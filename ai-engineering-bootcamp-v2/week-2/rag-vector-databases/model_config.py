"""OpenAI model names and generation settings from .env."""

from __future__ import annotations

import os

from env_utils import float_env


def answer_model() -> str:
    """Chat model for /ask step 2 — structured answer generation."""
    value = os.getenv("ANSWER_MODEL", os.getenv("CHAT_MODEL", "gpt-4o")).strip()
    return value or "gpt-4o"


def extraction_model() -> str:
    """Chat model for two-step step 1 — fact extraction from retrieved chunks."""
    value = os.getenv("EXTRACTION_MODEL", "").strip()
    if value:
        return value
    return answer_model()


def embedding_model() -> str:
    """Embedding model for question retrieval and document ingest."""
    value = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
    return value or "text-embedding-3-small"


def ragas_judge_model() -> str:
    """LLM used by RAGAS to score faithfulness and answer_correctness in eval."""
    value = os.getenv("RAGAS_JUDGE_MODEL", "gpt-4o-mini").strip()
    return value or "gpt-4o-mini"


def generation_temperature() -> float:
    return float_env("GENERATION_TEMPERATURE", 0.0)

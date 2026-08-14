"""Per-request retrieval mode for POST /agent (Fast = lite, Slow = full pipeline)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

from env_utils import bool_env

RetrievalMode = Literal["fast", "slow"]

_retrieval_mode: ContextVar[RetrievalMode | None] = ContextVar(
    "agent_retrieval_mode", default=None
)


def reset_retrieval_mode() -> None:
    """Clear mode at the start of each /agent request."""
    _retrieval_mode.set(None)


def set_retrieval_mode(mode: RetrievalMode | None) -> None:
    _retrieval_mode.set(mode)


def get_retrieval_mode() -> RetrievalMode | None:
    return _retrieval_mode.get()


def retrieval_lite_enabled() -> bool:
    """True when the client chose Fast or AGENT_LITE_RETRIEVAL env is set."""
    mode = _retrieval_mode.get()
    if mode == "fast":
        return True
    if mode == "slow":
        return False
    return bool_env("AGENT_LITE_RETRIEVAL", False)

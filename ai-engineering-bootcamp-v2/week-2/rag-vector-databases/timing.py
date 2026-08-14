"""Per-request latency spans for POST /agent (contextvar-scoped)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_timings: ContextVar[dict[str, float] | None] = ContextVar("agent_timings", default=None)


def reset_timings() -> None:
    """Clear timings at the start of each /agent request."""
    _timings.set({})


def get_timings() -> dict[str, float]:
    """Return accumulated span durations in milliseconds (may be empty)."""
    store = _timings.get()
    return dict(store) if store else {}


def record_event(name: str, ms: float) -> None:
    """Add milliseconds to a named span (accumulates if called multiple times)."""
    store = _timings.get()
    if store is None:
        return
    store[name] = store.get(name, 0.0) + ms


def start_span(name: str) -> float:
    """Begin a manual span; returns perf_counter start time."""
    return time.perf_counter()


def end_span(name: str, started_at: float) -> None:
    """End a manual span started with ``start_span``."""
    record_event(name, (time.perf_counter() - started_at) * 1000)


@contextmanager
def timed_span(name: str) -> Iterator[None]:
    """Context manager that records wall time for ``name`` in milliseconds."""
    started_at = start_span(name)
    try:
        yield
    finally:
        end_span(name, started_at)


def sorted_timings() -> list[tuple[str, float]]:
    """Return (name, ms) pairs sorted by duration descending."""
    return sorted(get_timings().items(), key=lambda item: item[1], reverse=True)

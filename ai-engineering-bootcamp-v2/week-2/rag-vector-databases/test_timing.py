"""Tests for per-request agent timing spans."""

from __future__ import annotations

import time

from timing import get_timings, record_event, reset_timings, timed_span


def test_reset_and_record_event():
    reset_timings()
    record_event("alpha", 10.5)
    record_event("alpha", 2.0)
    assert get_timings() == {"alpha": 12.5}


def test_timed_span_accumulates():
    reset_timings()
    with timed_span("sleepy"):
        time.sleep(0.02)
    timings = get_timings()
    assert timings["sleepy"] >= 15.0
    reset_timings()


def test_noop_when_not_reset():
    reset_timings()
    record_event("orphan", 1.0)
    assert get_timings() == {"orphan": 1.0}
    reset_timings()
    assert get_timings() == {}

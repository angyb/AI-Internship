"""Unit tests for health_checks.pinecone_error_detail — no live Pinecone calls."""

from health_checks import pinecone_error_detail


def test_pinecone_egress_limit_message() -> None:
    exc = RuntimeError(
        "[429] Request failed. You've reached your egress limit for the "
        "current month (10000000000 bytes). To continue reading data, "
        "upgrade your plan."
    )
    detail = pinecone_error_detail(exc)
    assert "egress limit" in detail.lower()
    assert "vector search is unavailable" in detail.lower()


def test_pinecone_generic_error_passthrough() -> None:
    detail = pinecone_error_detail(RuntimeError("connection timed out"))
    assert detail == "connection timed out"


def test_pinecone_generic_error_redacts_secrets() -> None:
    detail = pinecone_error_detail(
        RuntimeError("auth failed for Bearer sk-proj-abcdefghijklmnop")
    )
    assert "sk-proj-abcdefghijklmnop" not in detail
    assert "Bearer …" in detail or "sk-…" in detail

"""Unit tests for secret_redaction — no network."""

from __future__ import annotations

from secret_redaction import (
    read_env_secret,
    redact_secrets,
    safe_error_message,
    sanitize_for_client,
)


def test_redact_openai_and_pinecone_keys() -> None:
    raw = "Bearer sk-admin-abcdefghijklmnop PINECONE_API_KEY=pcsk_abcdefghijklmnop"
    redacted = redact_secrets(raw)
    assert "sk-admin-abcdefghijklmnop" not in redacted
    assert "pcsk_abcdefghijklmnop" not in redacted


def test_redact_illegal_header_value_without_leaking() -> None:
    raw = (
        "Illegal header value b'Bearer sk-admin-secret\\nPINECONE_API_KEY=pcsk_secret'"
    )
    redacted = redact_secrets(raw)
    assert "sk-admin-secret" not in redacted
    assert "pcsk_secret" not in redacted
    assert "Invalid API key format" in redacted


def test_redact_database_url() -> None:
    raw = "connection failed: postgresql://user:secretpass@host/db"
    redacted = redact_secrets(raw)
    assert "secretpass" not in redacted
    assert "postgresql://[redacted]" in redacted


def test_redact_gemini_key_query_param() -> None:
    fake_key = "AQ." + ("Ab8RN6KVt6zWONTtokUtNiQMdlmS7A5qhhZKyrXLylIB4x12bw"[::-1])
    raw = f"GET https://example.com/v1/models?key={fake_key} failed"
    redacted = redact_secrets(raw)
    assert fake_key not in redacted
    assert "key=…" in redacted


def test_read_env_secret_warns_on_multiline() -> None:
    import os

    os.environ["TEST_MULTILINE_SECRET"] = "line-one\nline-two"
    value, warning = read_env_secret("TEST_MULTILINE_SECRET")
    del os.environ["TEST_MULTILINE_SECRET"]
    assert value == "line-one"
    assert warning is not None
    assert "multiple lines" in warning


def test_safe_error_message_prefix() -> None:
    detail = safe_error_message(
        ValueError("failed with sk-proj-abcdefghijklmnop"),
        prefix="Retrieval failed",
    )
    assert detail.startswith("Retrieval failed:")
    assert "sk-proj-abcdefghijklmnop" not in detail


def test_sanitize_for_client_walks_nested_payload() -> None:
    payload = {
        "usage": {
            "openai": {
                "detail": "Illegal header value b'Bearer sk-admin-leaked'",
            }
        },
        "checks": [{"detail": "pcsk_leaked_key_in_text pcsk_abcdefghijklmnop"}],
    }
    sanitized = sanitize_for_client(payload)
    dumped = str(sanitized)
    assert "sk-admin-leaked" not in dumped
    assert "pcsk_abcdefghijklmnop" not in dumped

"""Postgres (and local fallback) persistence for Ask Z-Bot chat history + memory.

Stores chat sessions and their messages so the extension's History tab can list
past conversations and resume the current one after a refresh, error, or tab
closure. Persistence is best-effort: when ``DATABASE_URL`` is unset the whole
module degrades to no-ops so /ask and a basic /agent still work locally.

Schema:
  sessions(id, install_id, title, token_count, status, ended_reason, created_at, updated_at)
  messages(id, session_id, role, content, steps, error, prompt_tokens, total_tokens, created_at)
  user_memory(install_id, role, grade_band, created_at, updated_at)
  agent_asks(id, created_at)
  bm25_chunks(chunk_id, document_id, chunk_index, source, title, source_url, text)

Sessions are scoped by a SHA-256 hash of ``install_id`` (the extension's
anonymous per-install UUID) — there is no user login. Legacy rows that still
store the raw UUID are read and rewritten on the next write. ``bm25_chunks`` is
the durable keyword-index corpus so API boots do not re-download Pinecone.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session as OrmSession,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.types import DateTime

logger = logging.getLogger(__name__)

USER_MEMORY_FALLBACK_PATH = (
    Path(__file__).resolve().parent / "user_memory_store.json"
)


def _normalize_database_url(url: str) -> str:
    """Force the psycopg (v3) driver.

    SQLAlchemy maps a bare ``postgresql://`` URL to psycopg2, which we do not
    install. Render hands out ``postgresql://...`` (and sometimes the legacy
    ``postgres://``), so rewrite both to ``postgresql+psycopg://``.
    """
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_engine = None
_SessionFactory: sessionmaker[OrmSession] | None = None

if _DATABASE_URL:
    try:
        _engine = create_engine(
            _normalize_database_url(_DATABASE_URL),
            pool_pre_ping=True,
            pool_recycle=300,
            future=True,
        )
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    except Exception as exc:  # pragma: no cover - config/driver errors
        logger.warning("Failed to initialize database engine: %s", exc)
        _engine = None
        _SessionFactory = None


def database_enabled() -> bool:
    """True when a usable engine was configured from DATABASE_URL."""
    return _SessionFactory is not None


def ping() -> None:
    """Run a cheap connectivity check. Raises if the database is down."""
    if _engine is None:
        raise RuntimeError("DATABASE_URL is not set")
    from sqlalchemy import text

    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def hash_install_id(install_id: str) -> str:
    """SHA-256 hex of the presented install UUID (server-side storage key)."""
    return hashlib.sha256((install_id or "").encode("utf-8")).hexdigest()


def _install_lookup_keys(install_id: str) -> list[str]:
    """Hashed key plus raw UUID so legacy rows still match."""
    presented = (install_id or "").strip()
    if not presented:
        return []
    hashed = hash_install_id(presented)
    if hashed == presented:
        return [hashed]
    return [hashed, presented]


def _install_id_matches(stored: str | None, presented: str) -> bool:
    if not stored:
        return False
    return stored in _install_lookup_keys(presented)


class SessionOwnershipError(Exception):
    """Raised when a session_id exists but belongs to a different install."""


def _require_session_owner(stored: str | None, presented: str) -> None:
    if not _install_id_matches(stored, presented):
        raise SessionOwnershipError("session does not belong to this install")


def _migrate_session_install_id(row: ChatSession, presented: str) -> None:
    hashed = hash_install_id(presented)
    if row.install_id == presented and hashed != presented:
        row.install_id = hashed


def sum_assistant_tokens_since(since: datetime) -> dict[str, int]:
    """Sum Gemini token counts from assistant messages on/after ``since``."""
    if not database_enabled():
        return {"prompt_tokens": 0, "total_tokens": 0, "turns": 0}
    from sqlalchemy import func

    with _session_scope() as session:
        prompt = session.scalar(
            select(func.coalesce(func.sum(ChatMessage.prompt_tokens), 0)).where(
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= since,
            )
        )
        total = session.scalar(
            select(func.coalesce(func.sum(ChatMessage.total_tokens), 0)).where(
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= since,
            )
        )
        turns = session.scalar(
            select(func.count()).select_from(ChatMessage).where(
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= since,
            )
        )
    return {
        "prompt_tokens": int(prompt or 0),
        "total_tokens": int(total or 0),
        "turns": int(turns or 0),
    }


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    install_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    ended_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class UserMemory(Base):
    """Durable preference memory — survives process restart.

    Scoped by a hash of ``install_id`` (anonymous per-install UUID). For Path A, we store a
    single stable preference: ``role`` + one or more ``grade_band`` values (JSON list in DB).
    """

    __tablename__ = "user_memory"

    install_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="")
    grade_band: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Bm25Chunk(Base):
    """Durable BM25 corpus row — chunk text lives here, not in Pinecone metadata."""

    __tablename__ = "bm25_chunks"

    chunk_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(256), index=True, default="")
    chunk_index: Mapped[int] = mapped_column(Integer, default=-1)
    source: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")


class AgentAsk(Base):
    """One row per public /agent or /ask that counted toward the daily cap."""

    __tablename__ = "agent_asks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


def count_asks_since(since: datetime) -> int:
    """How many capped asks have been recorded on/after ``since``."""
    if not database_enabled():
        return 0
    with _session_scope() as session:
        n = session.scalar(
            select(func.count()).select_from(AgentAsk).where(AgentAsk.created_at >= since)
        )
    return int(n or 0)


def record_ask() -> None:
    """Count one ask toward the global daily cap. No-op without DATABASE_URL."""
    if not database_enabled():
        return
    with _session_scope() as session:
        session.add(AgentAsk())


def init_db() -> None:
    """Create tables if they do not exist. No-op when the DB is not configured."""
    if _engine is None:
        logger.info("DATABASE_URL not set — chat history persistence disabled.")
        return
    try:
        Base.metadata.create_all(_engine)
        _ensure_user_memory_grade_band_column()
        logger.info("Chat history and BM25 tables ready.")
    except Exception as exc:  # pragma: no cover - startup connectivity
        logger.warning("Chat history table creation failed: %s", exc)


def _ensure_user_memory_grade_band_column() -> None:
    """Widen grade_band to TEXT and allow JSON-encoded grade lists (best-effort)."""
    if _engine is None:
        return
    from sqlalchemy import text

    try:
        with _engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE user_memory ALTER COLUMN grade_band TYPE TEXT")
            )
            conn.commit()
    except Exception as exc:  # pragma: no cover - idempotent migration
        logger.debug("user_memory grade_band migration skipped: %s", exc)


def _serialize_grade_bands(grade_bands: list[str]) -> str:
    return json.dumps(grade_bands, ensure_ascii=False)


def _parse_grade_bands(raw: str | None) -> list[str]:
    text_value = (raw or "").strip()
    if not text_value:
        return []
    if text_value.startswith("["):
        try:
            parsed = json.loads(text_value)
        except json.JSONDecodeError:
            return [text_value]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [text_value]


def _memory_to_dict(install_id: str, role: str, grade_band_raw: str, updated_at: Any) -> dict[str, Any]:
    grade_bands = _parse_grade_bands(grade_band_raw)
    updated = updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at
    return {
        "install_id": install_id,
        "role": role,
        "grade_bands": grade_bands,
        "updated_at": updated,
    }


@contextmanager
def _session_scope() -> Iterator[OrmSession]:
    if _SessionFactory is None:
        raise RuntimeError("Database is not configured")
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _session_to_summary(row: ChatSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title or "",
        "token_count": row.token_count or 0,
        "status": row.status or "active",
        "ended_reason": row.ended_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _message_to_dict(row: ChatMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content or "",
        "steps": row.steps,
        "error": row.error,
        "prompt_tokens": row.prompt_tokens,
        "total_tokens": row.total_tokens,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def ensure_session(session_id: str, install_id: str) -> dict[str, Any]:
    """Return the session, creating it (status=active) if new."""
    hashed = hash_install_id(install_id)
    with _session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None:
            row = ChatSession(id=session_id, install_id=hashed, title="", status="active")
            db.add(row)
            db.flush()
        else:
            _require_session_owner(row.install_id, install_id)
            _migrate_session_install_id(row, install_id)
        return _session_to_summary(row)


def add_message(
    session_id: str,
    role: str,
    *,
    content: str = "",
    steps: Any | None = None,
    error: str | None = None,
    prompt_tokens: int | None = None,
    total_tokens: int | None = None,
) -> int:
    """Append a message to a session. Returns the new message id."""
    with _session_scope() as db:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content or "",
            steps=steps,
            error=error,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
        )
        db.add(msg)
        db.flush()
        return msg.id


def update_session(
    session_id: str,
    *,
    title: str | None = None,
    token_count: int | None = None,
    status: str | None = None,
    ended_reason: str | None = None,
) -> dict[str, Any] | None:
    """Patch mutable session fields. Returns the updated summary, or None if missing."""
    with _session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None:
            return None
        if title is not None:
            row.title = title
        if token_count is not None:
            row.token_count = token_count
        if status is not None:
            row.status = status
        if ended_reason is not None:
            row.ended_reason = ended_reason
        db.flush()
        return _session_to_summary(row)


def list_sessions(install_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Most-recently-updated sessions for an install, newest first."""
    keys = _install_lookup_keys(install_id)
    with _session_scope() as db:
        rows = (
            db.execute(
                select(ChatSession)
                .where(ChatSession.install_id.in_(keys))
                .order_by(ChatSession.updated_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        for row in rows:
            _migrate_session_install_id(row, install_id)
        return [_session_to_summary(row) for row in rows]


def get_session(session_id: str, install_id: str) -> dict[str, Any] | None:
    """Full session with messages, or None if it does not belong to this install."""
    with _session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None or not _install_id_matches(row.install_id, install_id):
            return None
        _migrate_session_install_id(row, install_id)
        summary = _session_to_summary(row)
        summary["messages"] = [_message_to_dict(m) for m in row.messages]
        return summary


def delete_session(session_id: str, install_id: str) -> bool:
    """Delete a session (and its messages). Returns True if a row was removed."""
    with _session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None or not _install_id_matches(row.install_id, install_id):
            return False
        db.execute(delete(ChatSession).where(ChatSession.id == session_id))
        return True


def _fallback_load_user_memory() -> dict[str, Any]:
    if not USER_MEMORY_FALLBACK_PATH.exists():
        return {}
    try:
        data = json.loads(USER_MEMORY_FALLBACK_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _fallback_save_user_memory(data: dict[str, Any]) -> None:
    USER_MEMORY_FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_MEMORY_FALLBACK_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_user_memory(install_id: str) -> dict[str, Any] | None:
    """Get durable preference memory for this install_id."""
    if not install_id:
        return None

    hashed = hash_install_id(install_id)

    if not database_enabled():
        data = _fallback_load_user_memory()
        row = data.get(hashed)
        if not isinstance(row, dict):
            row = data.get(install_id)
        if not isinstance(row, dict):
            return None
        if not (row.get("role") and (row.get("grade_bands") or row.get("grade_band"))):
            return None
        grade_bands = row.get("grade_bands")
        if isinstance(grade_bands, list):
            bands = [str(item).strip() for item in grade_bands if str(item).strip()]
        else:
            bands = _parse_grade_bands(str(row.get("grade_band") or ""))
        if not bands:
            return None
        return {
            "install_id": install_id,
            "role": str(row.get("role") or ""),
            "grade_bands": bands,
            "updated_at": row.get("updated_at"),
        }

    with _session_scope() as db:
        row = db.get(UserMemory, hashed)
        if row is None and hashed != install_id:
            row = db.get(UserMemory, install_id)
        if row is None:
            return None
        role = (row.role or "").strip()
        grade_bands = _parse_grade_bands(row.grade_band)
        if not role or not grade_bands:
            return None
        return _memory_to_dict(install_id, row.role, row.grade_band, row.updated_at)


def replace_user_memory(
    install_id: str,
    *,
    role: str,
    grade_bands: list[str],
) -> dict[str, Any]:
    """Replace (upsert) durable preference memory for this install_id."""
    now = datetime.now(timezone.utc).isoformat()
    role = (role or "").strip()
    grade_bands = [str(item).strip() for item in grade_bands if str(item).strip()]

    if not install_id:
        raise ValueError("install_id is required")
    if not role or not grade_bands:
        raise ValueError("role and grade_bands are required")

    serialized = _serialize_grade_bands(grade_bands)
    hashed = hash_install_id(install_id)

    if not database_enabled():
        data = _fallback_load_user_memory()
        data[hashed] = {
            "role": role,
            "grade_bands": grade_bands,
            "updated_at": now,
        }
        if hashed != install_id:
            data.pop(install_id, None)
        _fallback_save_user_memory(data)
        return {
            "install_id": install_id,
            "role": role,
            "grade_bands": grade_bands,
            "updated_at": now,
        }

    with _session_scope() as db:
        row = db.get(UserMemory, hashed)
        legacy = db.get(UserMemory, install_id) if hashed != install_id else None
        if row is None and legacy is not None:
            row = UserMemory(
                install_id=hashed,
                role=legacy.role,
                grade_band=legacy.grade_band,
            )
            db.add(row)
            db.delete(legacy)
        elif row is None:
            row = UserMemory(install_id=hashed)
            db.add(row)
        row.role = role
        row.grade_band = serialized
        db.flush()
        return _memory_to_dict(install_id, row.role, row.grade_band, row.updated_at)


def delete_user_memory(install_id: str) -> bool:
    """Delete preference memory for this install_id."""
    if not install_id:
        return False

    hashed = hash_install_id(install_id)

    if not database_enabled():
        data = _fallback_load_user_memory()
        removed = False
        if hashed in data:
            data.pop(hashed, None)
            removed = True
        if install_id in data:
            data.pop(install_id, None)
            removed = True
        if removed:
            _fallback_save_user_memory(data)
        return removed

    with _session_scope() as db:
        removed = False
        row = db.get(UserMemory, hashed)
        if row is not None:
            db.delete(row)
            removed = True
        if hashed != install_id:
            legacy = db.get(UserMemory, install_id)
            if legacy is not None:
                db.delete(legacy)
                removed = True
        return removed


def _chunk_row(row: dict[str, Any]) -> Bm25Chunk:
    return Bm25Chunk(
        chunk_id=str(row.get("chunk_id") or ""),
        document_id=str(row.get("document_id") or ""),
        chunk_index=int(row.get("chunk_index") if row.get("chunk_index") is not None else -1),
        source=str(row.get("source") or ""),
        title=str(row.get("title") or ""),
        source_url=str(row.get("source_url") or ""),
        text=str(row.get("text") or ""),
    )


def _chunk_to_dict(row: Bm25Chunk) -> dict[str, Any]:
    return {
        "chunk_id": row.chunk_id,
        "document_id": row.document_id or "",
        "chunk_index": row.chunk_index if row.chunk_index is not None else -1,
        "source": row.source or "",
        "title": row.title or "",
        "source_url": row.source_url or "",
        "text": row.text or "",
    }


def replace_document_chunks(document_id: str, rows: list[dict[str, Any]]) -> None:
    """Replace all BM25 rows for one document_id. No-op without DATABASE_URL."""
    if not database_enabled():
        return
    with _session_scope() as session:
        session.execute(delete(Bm25Chunk).where(Bm25Chunk.document_id == document_id))
        session.add_all([_chunk_row(row) for row in rows if row.get("chunk_id")])


def delete_document_chunks(document_id: str) -> None:
    """Delete BM25 rows for one document_id. No-op without DATABASE_URL."""
    if not database_enabled():
        return
    with _session_scope() as session:
        session.execute(delete(Bm25Chunk).where(Bm25Chunk.document_id == document_id))


def clear_bm25_chunks() -> None:
    """Truncate the BM25 corpus table. No-op without DATABASE_URL."""
    if not database_enabled():
        return
    with _session_scope() as session:
        session.execute(delete(Bm25Chunk))


def replace_all_bm25_chunks(rows: list[dict[str, Any]]) -> None:
    """Replace the entire BM25 corpus table. No-op without DATABASE_URL."""
    if not database_enabled():
        return
    with _session_scope() as session:
        session.execute(delete(Bm25Chunk))
        session.add_all([_chunk_row(row) for row in rows if row.get("chunk_id")])


def load_all_bm25_chunks() -> list[dict[str, Any]]:
    """Return every BM25 corpus row, or [] when the DB is unset/unavailable."""
    if not database_enabled():
        return []
    with _session_scope() as session:
        rows = session.execute(select(Bm25Chunk)).scalars().all()
        return [_chunk_to_dict(row) for row in rows]


def count_bm25_chunks() -> int:
    """Row count in bm25_chunks, or 0 when the DB is unset."""
    if not database_enabled():
        return 0
    from sqlalchemy import func

    with _session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(Bm25Chunk)) or 0)

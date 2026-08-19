"""Postgres (and local fallback) persistence for Ask Z-Bot chat history + memory.

Stores chat sessions and their messages so the extension's History tab can list
past conversations and resume the current one after a refresh, error, or tab
closure. Persistence is best-effort: when ``DATABASE_URL`` is unset the whole
module degrades to no-ops so /ask and a basic /agent still work locally.

Schema:
  sessions(id, install_id, title, token_count, status, ended_reason, created_at, updated_at)
  messages(id, session_id, role, content, steps, error, prompt_tokens, total_tokens, created_at)
  user_memory(install_id, role, grade_band, created_at, updated_at)
  bm25_chunks(chunk_id, document_id, chunk_index, source, title, source_url, text)

Sessions are scoped by ``install_id`` (the extension's anonymous per-install
UUID) — there is no user login. ``bm25_chunks`` is the durable keyword-index
corpus so API boots do not re-download Pinecone.
"""

from __future__ import annotations

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

    Scoped by ``install_id`` (anonymous per-install UUID). For Path A, we store a
    single stable preference pair: ``role`` + ``grade_band``.
    """

    __tablename__ = "user_memory"

    install_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="")
    grade_band: Mapped[str] = mapped_column(String(64), default="")
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


def init_db() -> None:
    """Create tables if they do not exist. No-op when the DB is not configured."""
    if _engine is None:
        logger.info("DATABASE_URL not set — chat history persistence disabled.")
        return
    try:
        Base.metadata.create_all(_engine)
        logger.info("Chat history and BM25 tables ready.")
    except Exception as exc:  # pragma: no cover - startup connectivity
        logger.warning("Chat history table creation failed: %s", exc)


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
    with _session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None:
            row = ChatSession(id=session_id, install_id=install_id, title="", status="active")
            db.add(row)
            db.flush()
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
    with _session_scope() as db:
        rows = (
            db.execute(
                select(ChatSession)
                .where(ChatSession.install_id == install_id)
                .order_by(ChatSession.updated_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [_session_to_summary(row) for row in rows]


def get_session(session_id: str, install_id: str) -> dict[str, Any] | None:
    """Full session with messages, or None if it does not belong to this install."""
    with _session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None or row.install_id != install_id:
            return None
        summary = _session_to_summary(row)
        summary["messages"] = [_message_to_dict(m) for m in row.messages]
        return summary


def delete_session(session_id: str, install_id: str) -> bool:
    """Delete a session (and its messages). Returns True if a row was removed."""
    with _session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None or row.install_id != install_id:
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

    if not database_enabled():
        data = _fallback_load_user_memory()
        row = data.get(install_id)
        if not isinstance(row, dict):
            return None
        if not (row.get("role") and row.get("grade_band")):
            return None
        return {
            "install_id": install_id,
            "role": str(row.get("role") or ""),
            "grade_band": str(row.get("grade_band") or ""),
            "updated_at": row.get("updated_at"),
        }

    with _session_scope() as db:
        row = db.get(UserMemory, install_id)
        if row is None:
            return None
        role = (row.role or "").strip()
        grade_band = (row.grade_band or "").strip()
        if not role or not grade_band:
            return None
        return {
            "install_id": row.install_id,
            "role": row.role,
            "grade_band": row.grade_band,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def replace_user_memory(
    install_id: str,
    *,
    role: str,
    grade_band: str,
) -> dict[str, Any]:
    """Replace (upsert) durable preference memory for this install_id."""
    now = datetime.now(timezone.utc).isoformat()
    role = (role or "").strip()
    grade_band = (grade_band or "").strip()

    if not install_id:
        raise ValueError("install_id is required")
    if not role or not grade_band:
        raise ValueError("role and grade_band are required")

    if not database_enabled():
        data = _fallback_load_user_memory()
        data[install_id] = {"role": role, "grade_band": grade_band, "updated_at": now}
        _fallback_save_user_memory(data)
        return {"install_id": install_id, "role": role, "grade_band": grade_band, "updated_at": now}

    with _session_scope() as db:
        row = db.get(UserMemory, install_id)
        if row is None:
            row = UserMemory(install_id=install_id)
            db.add(row)
        row.role = role
        row.grade_band = grade_band
        db.flush()
        return {
            "install_id": row.install_id,
            "role": row.role,
            "grade_band": row.grade_band,
            "updated_at": row.updated_at.isoformat() if row.updated_at else now,
        }


def delete_user_memory(install_id: str) -> bool:
    """Delete preference memory for this install_id."""
    if not install_id:
        return False

    if not database_enabled():
        data = _fallback_load_user_memory()
        if install_id in data:
            data.pop(install_id, None)
            _fallback_save_user_memory(data)
            return True
        return False

    with _session_scope() as db:
        row = db.get(UserMemory, install_id)
        if row is None:
            return False
        db.delete(row)
        return True


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

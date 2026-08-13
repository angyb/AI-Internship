"""Postgres persistence for Ask Z-Bot chat history.

Stores chat sessions and their messages so the extension's History tab can list
past conversations and resume the current one after a refresh, error, or tab
closure. Persistence is best-effort: when ``DATABASE_URL`` is unset the whole
module degrades to no-ops so /ask and a basic /agent still work locally.

Schema:
  sessions(id, install_id, title, token_count, status, ended_reason, created_at, updated_at)
  messages(id, session_id, role, content, steps, error, prompt_tokens, total_tokens, created_at)

Sessions are scoped by ``install_id`` (the extension's anonymous per-install
UUID) — there is no user login.
"""

from __future__ import annotations

import logging
import os
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


def init_db() -> None:
    """Create tables if they do not exist. No-op when the DB is not configured."""
    if _engine is None:
        logger.info("DATABASE_URL not set — chat history persistence disabled.")
        return
    try:
        Base.metadata.create_all(_engine)
        logger.info("Chat history tables ready.")
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

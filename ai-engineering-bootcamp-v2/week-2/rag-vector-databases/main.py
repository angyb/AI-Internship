"""Week 2 RAG API — ingest Zearn docs into Pinecone and answer with retrieval."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from openai import APIError, OpenAI
from pydantic import BaseModel, Field, ValidationError

from agent_security import (
    record_telemetry_event,
    require_agent_access,
    telemetry_enabled,
)
import db
from env_utils import bool_env

from ingest import (
    RetrievedChunk,
    apply_diverse_filter,
    chunk_ids_for_context,
    ingest_documents,
    ingest_text,
    prepare_context_chunks,
    resolve_retrieval_filters,
    retrieve_chunks_diverse,
    retrieve_chunks_hybrid,
)
from generation_config import prompt_substitution_vars
from model_config import answer_model, extraction_model, generation_temperature
from question_classifier import QuestionType, classify_question
from question_prompts import (
    get_fact_extraction_template,
    get_grounding_template,
    get_single_step_template,
)
from retrieval_config import (
    chunk_overlap as configured_chunk_overlap,
    chunk_size as configured_chunk_size,
    max_chunks_per_document,
    max_context_chunks,
    max_context_chunks_enabled,
    neighbor_chunk_radius,
    neighbor_chunks_enabled,
    neighbor_merge_enabled,
    retrieval_fetch_k,
    retrieval_k,
)

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

logger = logging.getLogger(__name__)


def hybrid_search_enabled() -> bool:
    return bool_env("HYBRID_SEARCH", True)


def two_step_generation_enabled() -> bool:
    return bool_env("TWO_STEP_GENERATION", True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        db.init_db()
    except Exception as exc:
        logger.warning("Chat history DB init failed: %s", exc)

    if hybrid_search_enabled():
        from bm25_index import get_bm25_index

        start = time.perf_counter()
        try:
            chunk_count = get_bm25_index().rebuild_from_pinecone()
            elapsed = time.perf_counter() - start
            logger.info("BM25 index rebuilt: %d chunks in %.1fs", chunk_count, elapsed)
        except Exception as exc:
            logger.warning("BM25 rebuild from Pinecone failed: %s", exc)

    from rerank import (
        context_order_by_rerank_score_enabled,
        relevance_filter_enabled,
        rerank_enabled,
        warmup_reranker,
    )

    if rerank_enabled() or relevance_filter_enabled() or context_order_by_rerank_score_enabled():
        def _warmup_reranker_background() -> None:
            start = time.perf_counter()
            try:
                warmup_reranker()
                elapsed = time.perf_counter() - start
                if elapsed > 0.01:
                    logger.info("Cross-encoder reranker ready in %.1fs", elapsed)
            except Exception as exc:
                logger.warning("Cross-encoder reranker warmup failed: %s", exc)

        threading.Thread(
            target=_warmup_reranker_background,
            name="rerank-warmup",
            daemon=True,
        ).start()

    yield


app = FastAPI(title="Week 2 RAG API", lifespan=lifespan)
client = OpenAI()

DEFAULT_MODEL = answer_model()

# Conversational context guardrail — the extension warns at 90% and hard-blocks
# once the running context (latest turn's total tokens) reaches this limit.
CONTEXT_TOKEN_LIMIT = int(os.getenv("CONTEXT_TOKEN_LIMIT", "100000"))


def title_model() -> str:
    """Small chat model used to name a session by its topic."""
    value = os.getenv("TITLE_MODEL", "gpt-4o-mini").strip()
    return value or "gpt-4o-mini"

MODEL_PRICES_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "o3-mini": (0.0011, 0.0044),
}


class Answer(BaseModel):
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    sources_needed: bool


class AskRequest(BaseModel):
    question: str
    force_bad: bool = False
    document_ids: list[str] = Field(
        default_factory=list,
        description="Optional metadata filter — restrict retrieval to these document_id values.",
    )
    exclude_document_ids: list[str] | None = Field(
        default=None,
        description=(
            "Omit these document_id values from retrieval. "
            "Omit this field to use EXCLUDE_DOCUMENT_IDS env (default: employee_handbook). "
            "Pass [] to search the full index."
        ),
    )
    model: str | None = Field(
        default=None,
        description=f"OpenAI chat model for answer generation. Omit to use ANSWER_MODEL env ({answer_model()}).",
        examples=["gpt-4o", "gpt-4o-mini", "o3-mini"],
    )


class AskResponse(BaseModel):
    answer: Answer
    tokens_used: int
    model: str
    latency_ms: int
    cost_usd: float
    sources: list[str]
    chunk_ids: list[str]
    question_type: str = Field(
        default="general",
        description="Heuristic question-type route used for step 1/2 prompts.",
    )


class IngestResponse(BaseModel):
    document_id: str
    chunks_indexed: int
    status: str
    vectors_cleared: int


class IngestDocumentRequest(BaseModel):
    document_id: str = Field(description="Identifier stored in Pinecone metadata for retrieval citations.")
    text: str = Field(description="Raw document text to chunk, embed, and upsert.")


class RetrieveRequest(BaseModel):
    question: str
    use_hybrid: bool = Field(
        default=True,
        description="Combine dense vector search with BM25 keyword search (RRF fusion).",
    )
    use_rerank: bool | None = Field(
        default=None,
        description="Rerank candidates with a local cross-encoder. Omit to use RERANK_ENABLED env.",
    )
    document_ids: list[str] = Field(
        default_factory=list,
        description="Optional metadata filter — restrict retrieval to these document_id values.",
    )
    exclude_document_ids: list[str] | None = Field(
        default=None,
        description=(
            "Omit these document_id values from retrieval. "
            "Omit this field to use EXCLUDE_DOCUMENT_IDS env (default: employee_handbook). "
            "Pass [] to search the full index."
        ),
    )


class RetrievedChunkOut(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    source: str


class RetrieveResponse(BaseModel):
    chunks: list[RetrievedChunkOut]


class AgentStep(BaseModel):
    phase: str
    author: str | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: str | None = None
    text: str | None = None


class HistoryTurn(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str = ""


class AgentRequest(BaseModel):
    question: str
    session_id: str | None = Field(
        default=None,
        description="Client-generated chat session UUID. Enables history persistence.",
    )
    install_id: str | None = Field(
        default=None,
        description="Anonymous per-install UUID that owns the session.",
    )
    history: list[HistoryTurn] = Field(
        default_factory=list,
        description="Prior conversation turns (chronological, excluding this question).",
    )


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AgentResponse(BaseModel):
    answer: str
    steps: list[AgentStep]
    session_id: str | None = None
    title: str | None = None
    token_count: int = 0
    context_token_limit: int = 0
    usage: TokenUsage = Field(default_factory=TokenUsage)


class HistorySessionSummary(BaseModel):
    id: str
    title: str = ""
    token_count: int = 0
    status: str = "active"
    ended_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class HistoryMessage(BaseModel):
    id: int
    role: str
    content: str = ""
    steps: list[AgentStep] | None = None
    error: str | None = None
    prompt_tokens: int | None = None
    total_tokens: int | None = None
    created_at: str | None = None


class HistorySessionDetail(HistorySessionSummary):
    messages: list[HistoryMessage] = Field(default_factory=list)


class HistoryListResponse(BaseModel):
    sessions: list[HistorySessionSummary]


class HistoryPatchRequest(BaseModel):
    install_id: str
    title: str | None = None
    status: str | None = None
    ended_reason: str | None = None


class TelemetryRequest(BaseModel):
    event: str = Field(description="Short event name, e.g. client_error")
    message: str = Field(default="", description="Sanitized error/detail text (no questions)")
    install_id: str = Field(default="", description="Anonymous extension install UUID")
    extension_version: str = Field(default="", description="Extension version string")


class EvalRequest(BaseModel):
    pass


class EvalQuestionResult(BaseModel):
    question: str
    reference: str
    expected_document_ids: list[str]
    retrieved_document_ids: list[str]
    retrieval_hit: bool
    faithfulness: float | None
    answer_correctness: float | None
    answer: str
    sources_needed: bool


class EvalAverages(BaseModel):
    retrieval_hit: float
    faithfulness: float | None
    answer_correctness: float | None
    retrieval_hits: int
    question_count: int


class EvalConfig(BaseModel):
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    k: int | None = None
    fetch_k: int | None = None
    max_per_document: int | None = None
    hybrid_search: bool | None = None
    exclude_document_ids: list[str] = Field(default_factory=list)


class EvalResponse(BaseModel):
    golden_set: str
    mode: str
    config: EvalConfig
    averages: EvalAverages
    questions: list[EvalQuestionResult]


class EvalAgentRequest(BaseModel):
    regenerate: bool = Field(
        default=False,
        description="Re-run the agent on trace_questions.json before scoring (slow).",
    )


class AgentCheckResult(BaseModel):
    passed: bool
    reason: str


class AgentEvalRow(BaseModel):
    id: str
    question: str
    expected_outcome: str
    actual_outcome: str
    passed: bool
    checks: dict[str, AgentCheckResult]


class AgentEvalCheckStats(BaseModel):
    passed: int
    failed: int
    pass_rate: float


class AgentEvalSummary(BaseModel):
    trace_count: int
    all_checks_passed: int
    all_checks_pass_rate: float
    checks: dict[str, AgentEvalCheckStats]


class EvalAgentResponse(BaseModel):
    traces_file: str
    trace_count: int
    summary: AgentEvalSummary
    rows: list[AgentEvalRow]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
def ingest(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    clear_index: bool = True,
    body: IngestDocumentRequest | None = None,
) -> IngestResponse:
    """Ingest documents into Pinecone.

    With a JSON body ``{"document_id": "...", "text": "..."}``, chunks and upserts
    that single pasted document (replacing any prior vectors for the same document_id).

    With no body, loads the full week-2/documents corpus from disk. By default,
    clears the index before a full-corpus upsert.

    curl examples:
      curl -X POST "http://127.0.0.1:8000/ingest?chunk_size=800&chunk_overlap=100"
      curl -X POST "http://127.0.0.1:8000/ingest" \\
        -H "Content-Type: application/json" \\
        -d '{"document_id":"my-note","text":"Zearn supports closed captioning."}'
    """

    try:
        effective_chunk_size = chunk_size if chunk_size is not None else configured_chunk_size()
        effective_chunk_overlap = chunk_overlap if chunk_overlap is not None else configured_chunk_overlap()
        if body is not None:
            result = ingest_text(
                document_id=body.document_id,
                text=body.text,
                chunk_size=effective_chunk_size,
                chunk_overlap=effective_chunk_overlap,
            )
        else:
            result = ingest_documents(
                chunk_size=effective_chunk_size,
                chunk_overlap=effective_chunk_overlap,
                clear_index_first=clear_index,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Missing required environment variable: {exc.args[0]}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}") from exc

    return IngestResponse(
        document_id=result.document_id,
        chunks_indexed=result.chunks_indexed,
        status=result.status,
        vectors_cleared=result.vectors_cleared,
    )


def resolve_model(model: str | None) -> str:
    """Normalize model name; fall back to ANSWER_MODEL env for empty or Swagger placeholders."""
    default = answer_model()
    if not model:
        return default
    cleaned = model.strip()
    if not cleaned or cleaned.lower() == "string":
        return default
    return cleaned


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    default = answer_model()
    prices = MODEL_PRICES_PER_1K.get(model, MODEL_PRICES_PER_1K.get(default, (0.0025, 0.01)))
    input_per_1k, output_per_1k = prices
    return (prompt_tokens / 1000 * input_per_1k) + (completion_tokens / 1000 * output_per_1k)


def compute_generation_cost_usd(
    answer_model_name: str,
    answer_prompt_tokens: int,
    answer_completion_tokens: int,
    *,
    extraction_model_name: str | None = None,
    extraction_prompt_tokens: int = 0,
    extraction_completion_tokens: int = 0,
) -> float:
    cost = compute_cost_usd(answer_model_name, answer_prompt_tokens, answer_completion_tokens)
    if extraction_prompt_tokens or extraction_completion_tokens:
        cost += compute_cost_usd(
            extraction_model_name or extraction_model(),
            extraction_prompt_tokens,
            extraction_completion_tokens,
        )
    return cost


def _source_label(chunk: RetrievedChunk) -> str:
    if chunk.source_url:
        return chunk.source_url
    if chunk.title:
        return chunk.title
    return chunk.source or chunk.document_id or "unknown"


def format_retrieved_context(chunks: list[RetrievedChunk]) -> str:
    """Format top-k chunks for the grounding prompt."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        if chunk.merged_chunk_ids:
            chunk_label = ", ".join(chunk.merged_chunk_ids)
        else:
            chunk_label = chunk.chunk_id
        url_part = f" | url: {chunk.source_url}" if chunk.source_url else ""
        parts.append(
            f"[{i}] title: {chunk.title}{url_part} | document_id: {chunk.document_id} | chunk_id: {chunk_label}\n{chunk.text}"
        )
    return "\n\n".join(parts)


def retrieve_context(
    question: str,
    *,
    use_hybrid: bool = True,
    use_rerank: bool | None = None,
    document_ids: list[str] | None = None,
    exclude_document_ids: list[str] | None = None,
) -> tuple[list[RetrievedChunk], str, list[str], list[str]]:
    """Embed the question, retrieve top-k chunks, and format context."""
    from rerank import (
        filter_and_order_chunks_by_relevance,
        rerank_candidate_max_per_document,
        rerank_candidates_count,
        rerank_chunks,
        rerank_enabled,
    )

    filter_ids, exclude_ids = resolve_retrieval_filters(document_ids, exclude_document_ids)
    do_rerank = rerank_enabled() if use_rerank is None else use_rerank
    final_k = retrieval_k()
    final_max_per_doc = max_chunks_per_document()

    if do_rerank:
        candidate_k = rerank_candidates_count()
        candidate_max_per_doc = rerank_candidate_max_per_document()
    else:
        candidate_k = retrieval_fetch_k()
        candidate_max_per_doc = final_max_per_doc

    if use_hybrid and hybrid_search_enabled():
        candidates = retrieve_chunks_hybrid(
            question,
            k=candidate_k,
            fetch_k=candidate_k,
            max_per_document=candidate_max_per_doc,
            document_ids=filter_ids,
            exclude_document_ids=exclude_ids,
        )
    else:
        candidates = retrieve_chunks_diverse(
            question,
            k=candidate_k,
            fetch_k=candidate_k,
            max_per_document=candidate_max_per_doc,
            document_ids=filter_ids,
            exclude_document_ids=exclude_ids,
        )

    if do_rerank and candidates:
        candidates = rerank_chunks(question, candidates)

    chunks = apply_diverse_filter(
        candidates,
        k=final_k,
        max_per_document=final_max_per_doc,
    )

    context_cap = max_context_chunks() if max_context_chunks_enabled() else None
    chunks = prepare_context_chunks(
        chunks,
        radius=neighbor_chunk_radius(),
        expand_neighbors=neighbor_chunks_enabled(),
        merge_neighbors=neighbor_merge_enabled(),
        max_chunks=context_cap,
    )

    chunks = filter_and_order_chunks_by_relevance(question, chunks)

    if not chunks:
        return [], "", [], []

    context = format_retrieved_context(chunks)
    chunk_ids = chunk_ids_for_context(chunks)

    sources: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        label = _source_label(chunk)
        if label not in seen:
            seen.add(label)
            sources.append(label)

    return chunks, context, chunk_ids, sources


@app.post("/retrieve")
def retrieve(body: RetrieveRequest) -> RetrieveResponse:
    """Return top-k retrieved chunks with text (for eval and debugging)."""

    try:
        chunks, _context, _chunk_ids, _sources = retrieve_context(
            body.question,
            use_hybrid=body.use_hybrid,
            use_rerank=body.use_rerank,
            document_ids=body.document_ids or None,
            exclude_document_ids=body.exclude_document_ids,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Missing required environment variable: {exc.args[0]}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc

    return RetrieveResponse(
        chunks=[
            RetrievedChunkOut(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                text=chunk.text,
                source=chunk.source,
            )
            for chunk in chunks
        ]
    )


def generate_session_title(question: str, answer: str) -> str:
    """Name a session by its topic via a small LLM call; fall back to the question.

    Never raises — on any error, returns the first 100 characters of the question.
    """
    fallback = (question or "").strip()[:100] or "New chat"
    try:
        completion = client.chat.completions.create(
            model=title_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write a short, specific title (3-6 words, no quotes, no trailing "
                        "punctuation) describing the topic of this support chat."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nAnswer: {answer[:800]}",
                },
            ],
            temperature=0,
            max_tokens=20,
        )
        title = (completion.choices[0].message.content or "").strip().strip('"').strip()
        return title[:120] if title else fallback
    except Exception as exc:  # pragma: no cover - title is best-effort
        logger.warning("Session title generation failed: %s", exc)
        return fallback


def _persist_agent_turn(
    body: AgentRequest,
    answer: str,
    steps: list[dict[str, Any]],
    usage: dict[str, int],
) -> tuple[str | None, int]:
    """Save the user question + assistant answer, updating token count and title.

    Returns ``(title, token_count)``. Persistence is best-effort: any DB error is
    logged and swallowed so the user still gets their answer.
    """
    if not (db.database_enabled() and body.session_id and body.install_id):
        return None, usage.get("total_tokens", 0)

    try:
        summary = db.ensure_session(body.session_id, body.install_id)
        is_first_turn = not summary.get("title")
        db.add_message(body.session_id, "user", content=body.question)
        db.add_message(
            body.session_id,
            "assistant",
            content=answer,
            steps=steps or None,
            prompt_tokens=usage.get("prompt_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        title = summary.get("title") or None
        if is_first_turn:
            title = generate_session_title(body.question, answer)
        token_count = usage.get("total_tokens", 0)
        db.update_session(
            body.session_id,
            title=title,
            token_count=token_count,
            status="active",
        )
        return title, token_count
    except Exception as exc:
        logger.warning("Failed to persist chat turn: %s", exc)
        return None, usage.get("total_tokens", 0)


@app.post("/agent", dependencies=[Depends(require_agent_access)])
def agent_run(body: AgentRequest) -> AgentResponse:
    """Run the Zearn ADK support agent (search_zearn_doc + google_search_agent fallback).

    When ``AGENT_API_KEY`` is set, require matching ``X-API-Key`` / Bearer token.
    Rate-limited per ``X-Install-Id`` (preferred) or client IP.

    Conversational: pass ``history`` (prior turns) to give the agent memory, plus
    ``session_id`` + ``install_id`` to persist the chat for the History tab.
    """

    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_API_KEY is not set — required for POST /agent",
        )

    history = [{"role": turn.role, "content": turn.content} for turn in body.history]

    try:
        from zearn_support_agent import run_zearn_agent

        answer, steps, usage = run_zearn_agent(body.question, history)
    except HTTPException:
        raise
    except Exception as exc:
        # Persist the question (and the error) so the session survives a failure.
        if db.database_enabled() and body.session_id and body.install_id:
            try:
                db.ensure_session(body.session_id, body.install_id)
                db.add_message(body.session_id, "user", content=body.question)
                db.add_message(
                    body.session_id, "assistant", content="", error=str(exc)
                )
                db.update_session(body.session_id, status="error", ended_reason="error")
            except Exception as persist_exc:
                logger.warning("Failed to persist errored turn: %s", persist_exc)
        raise HTTPException(status_code=500, detail=f"Agent run failed: {exc}") from exc

    title, token_count = _persist_agent_turn(body, answer, steps, usage)

    return AgentResponse(
        answer=answer,
        steps=[AgentStep(**step) for step in steps],
        session_id=body.session_id,
        title=title,
        token_count=token_count,
        context_token_limit=CONTEXT_TOKEN_LIMIT,
        usage=TokenUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
    )


@app.get("/history/sessions", dependencies=[Depends(require_agent_access)])
def history_list(install_id: str) -> HistoryListResponse:
    """List a caller's saved chat sessions (newest first), scoped by install_id."""
    if not db.database_enabled():
        return HistoryListResponse(sessions=[])
    if not install_id:
        raise HTTPException(status_code=400, detail="install_id is required")
    try:
        rows = db.list_sessions(install_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"History lookup failed: {exc}") from exc
    return HistoryListResponse(
        sessions=[HistorySessionSummary(**row) for row in rows]
    )


@app.get("/history/sessions/{session_id}", dependencies=[Depends(require_agent_access)])
def history_get(session_id: str, install_id: str) -> HistorySessionDetail:
    """Return a full session transcript, if it belongs to this install_id."""
    if not db.database_enabled():
        raise HTTPException(status_code=404, detail="History not available")
    if not install_id:
        raise HTTPException(status_code=400, detail="install_id is required")
    try:
        row = db.get_session(session_id, install_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"History lookup failed: {exc}") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return HistorySessionDetail(**row)


@app.patch("/history/sessions/{session_id}", dependencies=[Depends(require_agent_access)])
def history_patch(session_id: str, body: HistoryPatchRequest) -> HistorySessionSummary:
    """Rename a session or mark it ended (e.g. on refresh/tab closure)."""
    if not db.database_enabled():
        raise HTTPException(status_code=404, detail="History not available")
    if not body.install_id:
        raise HTTPException(status_code=400, detail="install_id is required")
    existing = db.get_session(session_id, body.install_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        updated = db.update_session(
            session_id,
            title=body.title,
            status=body.status,
            ended_reason=body.ended_reason,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"History update failed: {exc}") from exc
    return HistorySessionSummary(**updated)


@app.delete("/history/sessions/{session_id}", dependencies=[Depends(require_agent_access)])
def history_delete(session_id: str, install_id: str) -> dict[str, Any]:
    """Delete a session and its messages, if owned by this install_id."""
    if not db.database_enabled():
        raise HTTPException(status_code=404, detail="History not available")
    if not install_id:
        raise HTTPException(status_code=400, detail="install_id is required")
    try:
        removed = db.delete_session(session_id, install_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"History delete failed: {exc}") from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "id": session_id}


@app.post("/telemetry")
def telemetry(body: TelemetryRequest) -> dict[str, str]:
    """Optional client error telemetry (opt-in from the extension). Disabled unless TELEMETRY_ENABLED=true."""

    if not telemetry_enabled():
        return {"status": "disabled"}

    record_telemetry_event(
        event=body.event,
        message=body.message,
        install_id=body.install_id,
        extension_version=body.extension_version,
    )
    return {"status": "ok"}


def build_fact_extraction_prompt(
    question: str,
    context: str,
    question_type: QuestionType,
) -> str:
    return get_fact_extraction_template(question_type).substitute(
        context=context,
        question=question,
        **prompt_substitution_vars(for_extraction=True),
    )


def build_grounding_prompt(
    question: str,
    context: str,
    question_type: QuestionType,
    *,
    extracted_facts: str | None = None,
) -> str:
    prompt_vars = prompt_substitution_vars(for_extraction=False)
    if extracted_facts is not None:
        return get_grounding_template(question_type).substitute(
            extracted_facts=extracted_facts,
            question=question,
            **prompt_vars,
        )

    empty_context = "(No relevant chunks were retrieved.)"
    if not context.strip():
        context = empty_context

    return get_single_step_template(question_type).substitute(
        context=context,
        question=question,
        **prompt_vars,
    )


def extract_facts(
    question: str,
    context: str,
    model: str,
    question_type: QuestionType,
) -> tuple[str, int, int, int]:
    """Step 1 — pull grouped facts from retrieved chunks (plain-text completion)."""
    prompt = build_fact_extraction_prompt(question, context, question_type)
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=generation_temperature(),
    )

    facts = (completion.choices[0].message.content or "").strip()
    usage = completion.usage
    total = usage.total_tokens if usage else 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    return facts, total, prompt_tokens, completion_tokens


def generate_grounded_answer(
    question: str,
    context: str,
    model: str,
    *,
    force_bad: bool = False,
    question_type: QuestionType | None = None,
) -> tuple[Answer, int, int, int, QuestionType, int, int]:
    """Step 1 extract facts (optional), step 2 structured answer.

    Returns extraction prompt/completion token counts (0 when single-step).
    """
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    extraction_prompt_tokens = 0
    extraction_completion_tokens = 0
    route = question_type or classify_question(question)
    logger.debug("Question routed to prompt type: %s", route)

    if not context.strip():
        prompt = build_grounding_prompt(
            question,
            context,
            route,
            extracted_facts="(No relevant chunks were retrieved.)",
        )
    elif two_step_generation_enabled():
        extract_model = extraction_model()
        facts, step_tokens, step_prompt_tokens, step_completion_tokens = extract_facts(
            question, context, extract_model, route
        )
        extraction_prompt_tokens = step_prompt_tokens
        extraction_completion_tokens = step_completion_tokens
        total_tokens += step_tokens
        prompt_tokens += step_prompt_tokens
        completion_tokens += step_completion_tokens
        logger.debug("Fact extraction model: %s", extract_model)
        prompt = build_grounding_prompt(
            question,
            context,
            route,
            extracted_facts=facts or "(No facts extracted.)",
        )
    else:
        prompt = build_grounding_prompt(question, context, route)

    if force_bad:
        answer, step_tokens, step_prompt_tokens, step_completion_tokens = call_model_unsafe(
            prompt, model
        )
    else:
        answer, step_tokens, step_prompt_tokens, step_completion_tokens = call_model_structured(
            prompt, model
        )

    total_tokens += step_tokens
    prompt_tokens += step_prompt_tokens
    completion_tokens += step_completion_tokens
    answer_prompt_tokens = step_prompt_tokens
    answer_completion_tokens = step_completion_tokens
    return (
        answer,
        total_tokens,
        answer_prompt_tokens,
        answer_completion_tokens,
        route,
        extraction_prompt_tokens,
        extraction_completion_tokens,
    )


def call_model_structured(prompt: str, model: str) -> tuple[Answer, int, int, int]:
    """Session 1 generation path — structured output with schema validation."""
    completion = client.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=Answer,
        temperature=generation_temperature(),
    )

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Model returned no parseable structured output")

    usage = completion.usage
    total = usage.total_tokens if usage else 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    return parsed, total, prompt_tokens, completion_tokens


def call_model_unsafe(prompt: str, model: str) -> tuple[Answer, int, int, int]:
    """Session 1 guardrail demo path — free-form JSON, validated locally."""
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\n"
                    "Reply with ONLY a JSON object using keys answer, confidence, sources_needed. "
                    "Set confidence to the string 'very high' (not a number)."
                ),
            }
        ],
    )

    raw = completion.choices[0].message.content or ""
    answer = Answer.model_validate_json(raw)

    usage = completion.usage
    total = usage.total_tokens if usage else 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    return answer, total, prompt_tokens, completion_tokens


@app.post("/ask")
def ask(body: AskRequest) -> AskResponse:
    """Retrieve context from Pinecone, then answer with structured output."""

    model = resolve_model(body.model)
    last_error: str | None = None

    try:
        _chunks, context, chunk_ids, sources = retrieve_context(
            body.question,
            document_ids=body.document_ids or None,
            exclude_document_ids=body.exclude_document_ids,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Missing required environment variable: {exc.args[0]}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc

    for attempt in range(2):
        try:
            start = time.perf_counter()

            use_bad_path = body.force_bad and attempt == 0
            question_type = classify_question(body.question)
            answer, tokens_used, answer_prompt_tokens, answer_completion_tokens, route, ext_prompt_tokens, ext_completion_tokens = generate_grounded_answer(
                body.question,
                context,
                model,
                force_bad=use_bad_path,
                question_type=question_type,
            )

            latency_ms = int((time.perf_counter() - start) * 1000)
            cost_usd = compute_generation_cost_usd(
                model,
                answer_prompt_tokens,
                answer_completion_tokens,
                extraction_model_name=extraction_model() if ext_prompt_tokens or ext_completion_tokens else None,
                extraction_prompt_tokens=ext_prompt_tokens,
                extraction_completion_tokens=ext_completion_tokens,
            )

            return AskResponse(
                answer=answer,
                tokens_used=tokens_used,
                model=model,
                latency_ms=latency_ms,
                cost_usd=round(cost_usd, 6),
                sources=sources,
                chunk_ids=chunk_ids,
                question_type=route,
            )
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            continue
        except APIError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"OpenAI API error: {exc.message}",
            ) from exc

    raise HTTPException(
        status_code=502,
        detail=f"Model response failed schema validation after retry: {last_error}",
    )


@app.post("/eval-agent")
def run_agent_eval_endpoint(body: EvalAgentRequest | None = None) -> EvalAgentResponse:
    """Run deterministic pass/fail checks on committed agent traces (Week 4 TRACE)."""

    from pathlib import Path

    from agent_trace import DEFAULT_TRACES, capture_traces
    from eval_agent import load_eval_result, run_agent_eval

    traces_dir = Path(__file__).resolve().parent / "traces"
    before_path = traces_dir / "eval_before.json"
    after_path = traces_dir / "eval_after.json"

    regenerate = bool(body and body.regenerate)
    if regenerate:
        if not os.getenv("GOOGLE_API_KEY"):
            raise HTTPException(
                status_code=500,
                detail="GOOGLE_API_KEY is not set — required to regenerate traces",
            )
        try:
            capture_traces()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Trace capture failed: {exc}",
            ) from exc

    try:
        result = run_agent_eval(traces_path=DEFAULT_TRACES)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent eval failed: {exc}") from exc

    summary = result["summary"]
    return EvalAgentResponse(
        traces_file=result["traces_file"],
        trace_count=result["trace_count"],
        summary=AgentEvalSummary(
            trace_count=summary["trace_count"],
            all_checks_passed=summary["all_checks_passed"],
            all_checks_pass_rate=summary["all_checks_pass_rate"],
            checks={
                name: AgentEvalCheckStats(**stats)
                for name, stats in (summary.get("checks") or {}).items()
            },
        ),
        rows=[
            AgentEvalRow(
                id=row["id"],
                question=row["question"],
                expected_outcome=row["expected_outcome"],
                actual_outcome=row["actual_outcome"],
                passed=row["passed"],
                checks={
                    name: AgentCheckResult(**check)
                    for name, check in (row.get("checks") or {}).items()
                },
            )
            for row in result["rows"]
        ],
        before=load_eval_result(before_path),
        after=load_eval_result(after_path),
    )


@app.post("/eval")
def run_golden_eval(body: EvalRequest | None = None) -> EvalResponse:
    """Run golden-set evaluation (retrieval + /ask + RAGAS) on this server."""

    from eval_golden import DEFAULT_GOLDEN_SET, run_eval

    try:
        result = run_eval(
            DEFAULT_GOLDEN_SET,
            verbose=False,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Missing required environment variable: {exc.args[0]}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc

    averages = result["averages"]
    config = result.get("config", {})
    return EvalResponse(
        golden_set=result["golden_set"],
        mode=result["mode"],
        config=EvalConfig(
            chunk_size=config.get("chunk_size"),
            chunk_overlap=config.get("chunk_overlap"),
            k=config.get("k"),
            fetch_k=config.get("fetch_k"),
            max_per_document=config.get("max_per_document"),
            hybrid_search=config.get("hybrid_search"),
            exclude_document_ids=config.get("exclude_document_ids") or [],
        ),
        averages=EvalAverages(
            retrieval_hit=averages["retrieval_hit"],
            faithfulness=averages["faithfulness"],
            answer_correctness=averages["answer_correctness"],
            retrieval_hits=averages["retrieval_hits"],
            question_count=averages["question_count"],
        ),
        questions=[EvalQuestionResult(**question) for question in result["questions"]],
    )

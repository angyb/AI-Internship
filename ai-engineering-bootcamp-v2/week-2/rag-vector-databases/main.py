"""Week 2 RAG API — ingest Zearn docs into Pinecone and answer with retrieval."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from string import Template

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import APIError, OpenAI
from pydantic import BaseModel, Field, ValidationError

from ingest import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    RetrievedChunk,
    ingest_documents,
    ingest_text,
    retrieve_chunks_diverse,
    retrieve_chunks_hybrid,
)

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

logger = logging.getLogger(__name__)


def hybrid_search_enabled() -> bool:
    return os.getenv("HYBRID_SEARCH", "true").lower() != "false"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if hybrid_search_enabled():
        from bm25_index import get_bm25_index

        start = time.perf_counter()
        try:
            chunk_count = get_bm25_index().rebuild_from_pinecone()
            elapsed = time.perf_counter() - start
            logger.info("BM25 index rebuilt: %d chunks in %.1fs", chunk_count, elapsed)
        except Exception as exc:
            logger.warning("BM25 rebuild from Pinecone failed: %s", exc)
    yield


app = FastAPI(title="Week 2 RAG API", lifespan=lifespan)
client = OpenAI()

DEFAULT_MODEL = "gpt-4o"
RETRIEVAL_K = 5
RETRIEVAL_FETCH_K = 10
MAX_CHUNKS_PER_DOCUMENT = 2

# Grounding prompt template — filled after retrieval with numbered chunks.
GROUNDING_PROMPT_TEMPLATE = Template("""\
Answer the question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
- Cite the document_id for each chunk you use in your answer (e.g. [document_id: accessibility]).
- If the context is insufficient to answer the question, refuse clearly in your answer \
and set sources_needed to true.
- Follow the question's requested format (e.g. bullet list, succinct, names only without descriptions).

Retrieved context:
$context

Question: $question""")

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
    model: str = Field(
        default=DEFAULT_MODEL,
        description="OpenAI model to use.",
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
    document_ids: list[str] = Field(
        default_factory=list,
        description="Optional metadata filter — restrict retrieval to these document_id values.",
    )


class RetrievedChunkOut(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    source: str


class RetrieveResponse(BaseModel):
    chunks: list[RetrievedChunkOut]


class EvalRequest(BaseModel):
    skip_northwind_upsert: bool = Field(
        default=True,
        description="Skip re-ingesting the Northwind handbook before eval (use when already indexed).",
    )


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


class EvalResponse(BaseModel):
    golden_set: str
    mode: str
    averages: EvalAverages
    questions: list[EvalQuestionResult]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
def ingest(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
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
        if body is not None:
            result = ingest_text(
                document_id=body.document_id,
                text=body.text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        else:
            result = ingest_documents(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
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
    """Normalize model name; fall back to default for empty or Swagger placeholders."""
    if not model:
        return DEFAULT_MODEL
    cleaned = model.strip()
    if not cleaned or cleaned.lower() == "string":
        return DEFAULT_MODEL
    return cleaned


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = MODEL_PRICES_PER_1K.get(model, MODEL_PRICES_PER_1K[DEFAULT_MODEL])
    input_per_1k, output_per_1k = prices
    return (prompt_tokens / 1000 * input_per_1k) + (completion_tokens / 1000 * output_per_1k)


def _source_label(chunk: RetrievedChunk) -> str:
    if chunk.source_url:
        return chunk.source_url
    if chunk.title:
        return chunk.title
    return chunk.source or "unknown"


def format_retrieved_context(chunks: list[RetrievedChunk]) -> str:
    """Format top-k chunks for the grounding prompt."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        parts.append(
            f"[{i}] chunk_id: {chunk.chunk_id} | document_id: {chunk.title}\n{chunk.text}"
        )
    return "\n\n".join(parts)


def retrieve_context(
    question: str,
    *,
    use_hybrid: bool = True,
    document_ids: list[str] | None = None,
) -> tuple[list[RetrievedChunk], str, list[str], list[str]]:
    """Embed the question, retrieve top-k chunks, and format context."""
    filter_ids = document_ids or None
    if use_hybrid and hybrid_search_enabled():
        chunks = retrieve_chunks_hybrid(
            question,
            k=RETRIEVAL_K,
            fetch_k=RETRIEVAL_FETCH_K,
            max_per_document=MAX_CHUNKS_PER_DOCUMENT,
            document_ids=filter_ids,
        )
    else:
        chunks = retrieve_chunks_diverse(
            question,
            k=RETRIEVAL_K,
            fetch_k=RETRIEVAL_FETCH_K,
            max_per_document=MAX_CHUNKS_PER_DOCUMENT,
            document_ids=filter_ids,
        )

    if not chunks:
        return [], "", [], []

    context = format_retrieved_context(chunks)
    chunk_ids = [chunk.chunk_id for chunk in chunks]

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
            document_ids=body.document_ids or None,
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
                document_id=chunk.title,
                text=chunk.text,
                source=chunk.source,
            )
            for chunk in chunks
        ]
    )


def build_grounding_prompt(question: str, context: str) -> str:
    if not context:
        return GROUNDING_PROMPT_TEMPLATE.substitute(
            context="(No relevant chunks were retrieved.)",
            question=question,
        )

    return GROUNDING_PROMPT_TEMPLATE.substitute(context=context, question=question)


def call_model_structured(prompt: str, model: str) -> tuple[Answer, int, int, int]:
    """Session 1 generation path — structured output with schema validation."""
    completion = client.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=Answer,
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
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Missing required environment variable: {exc.args[0]}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc

    prompt = build_grounding_prompt(body.question, context)

    for attempt in range(2):
        try:
            start = time.perf_counter()

            use_bad_path = body.force_bad and attempt == 0
            if use_bad_path:
                answer, tokens_used, prompt_tokens, completion_tokens = call_model_unsafe(
                    prompt, model
                )
            else:
                answer, tokens_used, prompt_tokens, completion_tokens = call_model_structured(
                    prompt, model
                )

            latency_ms = int((time.perf_counter() - start) * 1000)
            cost_usd = compute_cost_usd(model, prompt_tokens, completion_tokens)

            return AskResponse(
                answer=answer,
                tokens_used=tokens_used,
                model=model,
                latency_ms=latency_ms,
                cost_usd=round(cost_usd, 6),
                sources=sources,
                chunk_ids=chunk_ids,
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


@app.post("/eval")
def run_golden_eval(body: EvalRequest | None = None) -> EvalResponse:
    """Run golden-set evaluation (retrieval + /ask + RAGAS) on this server."""

    from eval_golden import DEFAULT_GOLDEN_SET, run_eval

    request = body or EvalRequest()
    try:
        result = run_eval(
            DEFAULT_GOLDEN_SET,
            skip_northwind_upsert=request.skip_northwind_upsert,
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
    return EvalResponse(
        golden_set=result["golden_set"],
        mode=result["mode"],
        averages=EvalAverages(
            retrieval_hit=averages["retrieval_hit"],
            faithfulness=averages["faithfulness"],
            answer_correctness=averages["answer_correctness"],
            retrieval_hits=averages["retrieval_hits"],
            question_count=averages["question_count"],
        ),
        questions=[EvalQuestionResult(**question) for question in result["questions"]],
    )

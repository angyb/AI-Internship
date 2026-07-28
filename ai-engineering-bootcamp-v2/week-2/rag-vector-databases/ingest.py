"""Load week-2 documents, chunk, embed, and upsert into Pinecone."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone
from pypdf import PdfReader

from bm25_index import ensure_bm25_ready, get_bm25_index

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

THIS_DIR = Path(__file__).resolve().parent
DOCS_DIR = THIS_DIR.parent / "documents"

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
UPSERT_BATCH_SIZE = 100
METADATA_TEXT_KEY = "text"
RRF_K = 60
INVISIBLE_CHAR_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060]")

DOCUMENT_GLOBS = (
    DOCS_DIR / "zendesk" / "md",
    DOCS_DIR / "zendesk" / "pdf",
    DOCS_DIR / "website" / "md",
    DOCS_DIR / "website" / "pdf",
    DOCS_DIR / "northwind",
)


@dataclass
class IngestResult:
    document_id: str
    chunks_indexed: int
    status: str
    vectors_cleared: int = 0


@dataclass
class RetrievedChunk:
    text: str
    source_url: str
    title: str
    source: str
    chunk_id: str = ""
    chunk_index: int = -1


@dataclass
class DebugRetrievedChunk:
    score: float
    document_id: str
    chunk_index: int
    source: str
    text: str
    chunk_id: str = ""
    rank: int = 0


@dataclass
class HybridDebugResult:
    dense: list[DebugRetrievedChunk]
    bm25: list[DebugRetrievedChunk]
    fused: list[DebugRetrievedChunk]


def _parse_markdown_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    metadata: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("'\"")
    return metadata, parts[2].strip()


def _strip_invisible_chars(text: str) -> str:
    return INVISIBLE_CHAR_RE.sub("", text)


def _load_markdown(path: Path) -> Document | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    frontmatter, body = _parse_markdown_frontmatter(raw)
    body = _strip_invisible_chars(body)
    if not body.strip():
        return None

    document_id = frontmatter.get("doc_id", path.stem)
    metadata = {
        "document_id": document_id,
        "source": str(path.relative_to(DOCS_DIR)),
        "title": frontmatter.get("title", path.stem),
        "source_url": frontmatter.get("source_url", ""),
    }
    return Document(page_content=body, metadata=metadata)


def _normalize_pdf_text(text: str) -> str:
    """Collapse PDF extraction whitespace so chunk boundaries land on words."""
    text = _strip_invisible_chars(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_pdf_page_texts(path: Path) -> list[tuple[int, str]]:
    """Return (page_number, raw_text) for each page. Uses pymupdf when available."""
    if fitz is not None:
        try:
            with fitz.open(str(path)) as pdf:
                return [
                    (page_number, page.get_text())
                    for page_number, page in enumerate(pdf, start=1)
                ]
        except OSError:
            return []

    try:
        reader = PdfReader(str(path))
    except OSError:
        return []

    return [
        (page_number, page.extract_text() or "")
        for page_number, page in enumerate(reader.pages, start=1)
    ]


def _load_pdf(path: Path) -> list[Document]:
    """Load one Document per non-empty PDF page."""
    base_metadata = {
        "document_id": path.stem,
        "source": str(path.relative_to(DOCS_DIR)),
        "title": path.stem,
        "source_url": "",
    }

    documents: list[Document] = []
    for page_number, raw_text in _extract_pdf_page_texts(path):
        body = _normalize_pdf_text(raw_text)
        if not body:
            continue
        documents.append(
            Document(
                page_content=body,
                metadata={**base_metadata, "page_number": page_number},
            )
        )
    return documents


def load_documents() -> list[Document]:
    documents: list[Document] = []

    for folder in DOCUMENT_GLOBS:
        if not folder.exists():
            continue

        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name == "manifest.json":
                continue

            if path.suffix.lower() == ".md":
                doc = _load_markdown(path)
                if doc is not None:
                    documents.append(doc)
            elif path.suffix.lower() == ".pdf":
                documents.extend(_load_pdf(path))
            else:
                continue

    return documents


def _make_splitter(
    chunk_size: int,
    chunk_overlap: int,
) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _is_pdf_page_document(document: Document) -> bool:
    return "page_number" in document.metadata


def chunk_text(
    text: str,
    document_id: str,
    source: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Document]:
    splitter = _make_splitter(chunk_size, chunk_overlap)
    doc = Document(
        page_content=text,
        metadata={"document_id": document_id, "source": source},
    )
    return splitter.split_documents([doc])


def chunk_documents(
    documents: list[Document],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Document]:
    splitter = _make_splitter(chunk_size, chunk_overlap)

    markdown_docs = [doc for doc in documents if not _is_pdf_page_document(doc)]
    pdf_page_docs = [doc for doc in documents if _is_pdf_page_document(doc)]

    chunks: list[Document] = []
    if markdown_docs:
        chunks.extend(splitter.split_documents(markdown_docs))

    for page_doc in pdf_page_docs:
        if len(page_doc.page_content) <= chunk_size:
            chunks.append(page_doc)
            continue
        chunks.extend(splitter.split_documents([page_doc]))

    return chunks


def _chunk_id(document_id: str, chunk_index: int) -> str:
    safe_id = str(document_id).replace("/", "_")
    return f"{safe_id}__chunk_{chunk_index}"


def _pinecone_index():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return pc.Index(host=os.environ["PINECONE_HOST"])


def clear_index() -> int:
    """Delete all vectors from the Pinecone index. Returns the prior vector count."""
    index = _pinecone_index()
    stats = index.describe_index_stats()
    previous_count = int(stats.total_vector_count or 0)
    if previous_count:
        index.delete(delete_all=True)
    get_bm25_index().clear()
    return previous_count


def _embeddings_client() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def _chunk_to_metadata(chunk: Document, chunk_index: int) -> dict[str, str | int]:
    metadata: dict[str, str | int] = {
        METADATA_TEXT_KEY: chunk.page_content[:35000],
        "document_id": str(chunk.metadata.get("document_id", "")),
        "chunk_index": chunk_index,
        "source": str(chunk.metadata.get("source", "")),
    }
    page_number = chunk.metadata.get("page_number")
    if page_number is not None:
        metadata["page_number"] = int(page_number)
    return metadata


def upsert_chunks(chunks: list[Document]) -> int:
    if not chunks:
        return 0

    embeddings = _embeddings_client()
    index = _pinecone_index()

    # Group chunks by document_id so chunk_index is per-document.
    by_document: dict[str, list[Document]] = {}
    for chunk in chunks:
        doc_id = str(chunk.metadata.get("document_id", "unknown"))
        by_document.setdefault(doc_id, []).append(chunk)

    total_indexed = 0
    pending_ids: list[str] = []
    pending_texts: list[str] = []
    pending_meta: list[tuple[Document, int]] = []

    def flush_batch() -> None:
        nonlocal total_indexed
        if not pending_ids:
            return
        vectors = embeddings.embed_documents(pending_texts)
        records = [
            {
                "id": chunk_id,
                "values": vector,
                "metadata": _chunk_to_metadata(chunk, chunk_index),
            }
            for chunk_id, vector, (chunk, chunk_index) in zip(
                pending_ids, vectors, pending_meta, strict=True
            )
        ]
        index.upsert(vectors=records)
        total_indexed += len(records)
        pending_ids.clear()
        pending_texts.clear()
        pending_meta.clear()

    for document_id, doc_chunks in by_document.items():
        for chunk_index, chunk in enumerate(doc_chunks):
            pending_ids.append(_chunk_id(document_id, chunk_index))
            pending_texts.append(chunk.page_content)
            pending_meta.append((chunk, chunk_index))
            if len(pending_ids) >= UPSERT_BATCH_SIZE:
                flush_batch()

    flush_batch()
    get_bm25_index().upsert_chunks(chunks, _chunk_id)
    return total_indexed


def delete_vectors_for_document(document_id: str) -> int:
    """Remove all vectors for one document_id before re-ingesting pasted text."""
    get_bm25_index().delete_document(document_id)
    index = _pinecone_index()
    index.delete(filter={"document_id": document_id})
    return 0


def ingest_text(
    document_id: str,
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    replace_existing: bool = True,
    source: str | None = None,
) -> IngestResult:
    """Chunk, embed, and upsert a single pasted document."""
    doc_id = document_id.strip()
    body = _strip_invisible_chars(text.strip())
    if not doc_id:
        raise ValueError("document_id must not be empty")
    if not body:
        raise ValueError("text must not be empty")

    doc_source = source or f"ui/{doc_id}"
    chunks = chunk_text(body, doc_id, doc_source, chunk_size, chunk_overlap)
    if not chunks:
        raise ValueError("No chunks produced from text")

    if replace_existing:
        delete_vectors_for_document(doc_id)

    chunks_indexed = upsert_chunks(chunks)
    return IngestResult(
        document_id=doc_id,
        chunks_indexed=chunks_indexed,
        status="ok",
        vectors_cleared=0,
    )


def ingest_file(
    path: Path | str,
    document_id: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    replace_existing: bool = True,
) -> IngestResult:
    """Read one text file from disk and upsert it without touching other documents."""
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise ValueError(f"File not found: {file_path}")

    text = file_path.read_text(encoding="utf-8")
    doc_id = (document_id or file_path.stem).strip()
    try:
        source = str(file_path.relative_to(DOCS_DIR))
    except ValueError:
        source = str(file_path)

    return ingest_text(
        document_id=doc_id,
        text=text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        replace_existing=replace_existing,
        source=source,
    )


def ingest_documents(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    clear_index_first: bool = True,
) -> IngestResult:
    raw_docs = load_documents()
    if not raw_docs:
        raise ValueError("No documents found to ingest")

    chunks = chunk_documents(raw_docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        raise ValueError("No chunks produced from document corpus")

    vectors_cleared = clear_index() if clear_index_first else 0
    chunks_indexed = upsert_chunks(chunks)

    return IngestResult(
        document_id="week-2/documents",
        chunks_indexed=chunks_indexed,
        status="ok",
        vectors_cleared=vectors_cleared,
    )


def retrieve_chunks(question: str, k: int = 3) -> list[RetrievedChunk]:
    embeddings = _embeddings_client()
    index = _pinecone_index()

    query_vector = embeddings.embed_query(question)
    results = index.query(vector=query_vector, top_k=k, include_metadata=True)

    return [_match_to_retrieved_chunk(match) for match in results.get("matches", [])]


def _match_to_retrieved_chunk(match: dict) -> RetrievedChunk:
    metadata = match.get("metadata") or {}
    document_id = str(metadata.get("document_id", ""))
    chunk_index_raw = metadata.get("chunk_index", -1)
    chunk_index = int(chunk_index_raw) if chunk_index_raw is not None else -1
    chunk_id = str(match.get("id") or _chunk_id(document_id, chunk_index))
    return RetrievedChunk(
        text=str(metadata.get(METADATA_TEXT_KEY, "")),
        source_url=str(metadata.get("source_url", "")),
        title=document_id,
        source=str(metadata.get("source", "")),
        chunk_id=chunk_id,
        chunk_index=chunk_index,
    )


def retrieve_chunks_bm25(question: str, k: int = 3) -> list[RetrievedChunk]:
    bm25_index = ensure_bm25_ready()
    chunks: list[RetrievedChunk] = []

    for chunk_id, _score in bm25_index.search(question, k=k):
        record = bm25_index.get_record(chunk_id)
        if record is None:
            continue
        chunks.append(
            RetrievedChunk(
                text=record.text,
                source_url=record.source_url,
                title=record.document_id,
                source=record.source,
                chunk_id=record.chunk_id,
                chunk_index=record.chunk_index,
            )
        )
    return chunks


def reciprocal_rank_fusion(
    dense_chunks: list[RetrievedChunk],
    bm25_chunks: list[RetrievedChunk],
    rrf_k: int = RRF_K,
) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for rank, chunk in enumerate(dense_chunks):
        chunk_map[chunk.chunk_id] = chunk
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)

    for rank, chunk in enumerate(bm25_chunks):
        chunk_map[chunk.chunk_id] = chunk
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)

    ranked_ids = sorted(scores, key=scores.get, reverse=True)
    return [chunk_map[chunk_id] for chunk_id in ranked_ids]


def _apply_diverse_filter(
    candidates: list[RetrievedChunk],
    k: int,
    max_per_document: int,
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    per_document: dict[str, int] = {}
    for chunk in candidates:
        doc_id = chunk.title or chunk.source
        if per_document.get(doc_id, 0) >= max_per_document:
            continue
        selected.append(chunk)
        per_document[doc_id] = per_document.get(doc_id, 0) + 1
        if len(selected) >= k:
            break
    return selected


def retrieve_chunks_hybrid(
    question: str,
    k: int = 6,
    fetch_k: int = 12,
    max_per_document: int = 2,
) -> list[RetrievedChunk]:
    """Combine dense Pinecone search with BM25 via reciprocal rank fusion."""

    fetch_k = max(fetch_k, k)
    dense_candidates = retrieve_chunks(question, k=fetch_k)
    bm25_candidates = retrieve_chunks_bm25(question, k=fetch_k)
    fused_candidates = reciprocal_rank_fusion(dense_candidates, bm25_candidates)
    return _apply_diverse_filter(fused_candidates, k=k, max_per_document=max_per_document)


def retrieve_chunks_diverse(
    question: str,
    k: int = 6,
    fetch_k: int = 12,
    max_per_document: int = 2,
) -> list[RetrievedChunk]:
    """Retrieve top chunks while limiting how many come from the same document.

    Fetches more candidates than k, then keeps the highest-scoring chunks subject
    to a per-document cap so one long PDF does not dominate the context window.
    """
    fetch_k = max(fetch_k, k)
    candidates = retrieve_chunks(question, k=fetch_k)
    return _apply_diverse_filter(candidates, k=k, max_per_document=max_per_document)


def debug_retrieve(question: str, k: int = 5) -> list[DebugRetrievedChunk]:
    """Embed a question and return top-k Pinecone matches with scores — no LLM."""

    embeddings = _embeddings_client()
    index = _pinecone_index()

    query_vector = embeddings.embed_query(question)
    results = index.query(vector=query_vector, top_k=k, include_metadata=True)

    chunks: list[DebugRetrievedChunk] = []
    for rank, match in enumerate(results.get("matches", []), start=1):
        metadata = match.get("metadata") or {}
        chunk_index = metadata.get("chunk_index", -1)
        document_id = str(metadata.get("document_id", ""))
        chunk_index_int = int(chunk_index) if chunk_index is not None else -1
        chunks.append(
            DebugRetrievedChunk(
                score=float(match.get("score", 0.0)),
                document_id=document_id,
                chunk_index=chunk_index_int,
                source=str(metadata.get("source", "")),
                text=str(metadata.get(METADATA_TEXT_KEY, "")),
                chunk_id=str(match.get("id") or _chunk_id(document_id, chunk_index_int)),
                rank=rank,
            )
        )
    return chunks


def _retrieved_to_debug(
    chunks: list[RetrievedChunk],
    scores: list[float] | None = None,
) -> list[DebugRetrievedChunk]:
    debug_chunks: list[DebugRetrievedChunk] = []
    for rank, chunk in enumerate(chunks, start=1):
        score = scores[rank - 1] if scores and rank - 1 < len(scores) else 0.0
        debug_chunks.append(
            DebugRetrievedChunk(
                score=score,
                document_id=chunk.title,
                chunk_index=chunk.chunk_index,
                source=chunk.source,
                text=chunk.text,
                chunk_id=chunk.chunk_id,
                rank=rank,
            )
        )
    return debug_chunks


def debug_retrieve_hybrid(question: str, k: int = 5) -> HybridDebugResult:
    """Return dense, BM25, and fused rankings side-by-side for debugging."""

    dense_chunks = retrieve_chunks(question, k=k)
    bm25_raw = get_bm25_index().search(question, k=k)
    bm25_chunks = retrieve_chunks_bm25(question, k=k)
    bm25_scores = [score for _chunk_id, score in bm25_raw]
    fused_chunks = reciprocal_rank_fusion(
        retrieve_chunks(question, k=max(k, 10)),
        retrieve_chunks_bm25(question, k=max(k, 10)),
    )[:k]

    return HybridDebugResult(
        dense=_retrieved_to_debug(dense_chunks),
        bm25=_retrieved_to_debug(bm25_chunks, bm25_scores),
        fused=_retrieved_to_debug(fused_chunks),
    )

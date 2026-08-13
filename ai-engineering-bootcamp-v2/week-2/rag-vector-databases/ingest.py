"""Load week-2 documents, chunk, embed, and upsert into Pinecone."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone
from pypdf import PdfReader

from bm25_index import ensure_bm25_ready, get_bm25_index
from model_config import embedding_model
from retrieval_config import chunk_overlap as configured_chunk_overlap
from retrieval_config import chunk_size as configured_chunk_size
from structure_chunking import soft_normalize_pdf_text, structure_chunk_document

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

THIS_DIR = Path(__file__).resolve().parent
DOCS_DIR = THIS_DIR.parent / "documents"

EMBEDDING_MODEL = "text-embedding-3-small"  # fallback label; use embedding_model() at runtime
DEFAULT_CHUNK_SIZE = 800  # fallback; ingest uses configured_chunk_size() when unset
DEFAULT_CHUNK_OVERLAP = 100
UPSERT_BATCH_SIZE = 100


def resolve_chunk_settings(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> tuple[int, int]:
    size = chunk_size if chunk_size is not None else configured_chunk_size()
    overlap = chunk_overlap if chunk_overlap is not None else configured_chunk_overlap()
    # Overlap must be strictly less than size or the splitter loops/raises.
    if overlap >= size:
        overlap = max(size - 1, 0)
    return size, overlap
METADATA_TEXT_KEY = "text"
RRF_K = 60
INVISIBLE_CHAR_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060]")
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)

# Word boundaries inside CamelCase / acronym runs. Digit→uppercase splits only when the
# uppercase letter starts a word (not G05M01-style codes where M is followed by digits).
CAMEL_BOUNDARY_RE = re.compile(
    r"(?<=[a-z])(?=[A-Z])"
    r"|(?<=[A-Z])(?=[A-Z][a-z])"
    r"|(?<=[a-z])(?=[0-9])"
    r"|(?<=[0-9])(?=[A-Z](?![0-9]))"
)

# Filenames often glue a lowercase connector onto the previous word ("K8withZearnMath").
# "and"/"to" are excluded when they appear inside words like "Admin" or "Login".
GLUED_CONNECTOR_RE = re.compile(
    r"(?<=[A-Za-z0-9])(and|for|from|of|through|to|with|within)(?=[A-Z])"
)

# Grade / band ranges in filenames: 6_8 -> 6-8 before other splitting.
GRADE_RANGE_RE = re.compile(r"(\d+)_(\d+)")

PDF_TITLE_SUFFIX = "(PDF)"

# Exact titles for PDFs where filename heuristics are wrong or ambiguous.
PDF_TITLE_OVERRIDES: dict[str, str] = {
    "G05M01_AssessmentRubric_CC": "G05M01 Assessment Rubric CC",
    "ParentandCaregiverGuidetoZearn": "Parent and Caregiver Guide to Zearn",
    "SupportingBluebonnetLearning6_8withZearnMath": (
        "Supporting Bluebonnet Learning 6-8 with Zearn Math"
    ),
    "SupportingMathNationSouthCarolina6_8withZearnMath": (
        "Supporting Math Nation South Carolina 6-8 with Zearn Math"
    ),
    "SupportingenVisionMathSouthCarolinaK8withZearnMath": (
        "Supporting enVision Math South Carolina K8 with Zearn Math"
    ),
    "Supportingi-ReadyClassroomSouthCarolinaK-8withZearnMath": (
        "Supporting i-Ready Classroom South Carolina K8 with Zearn Math"
    ),
    "SupportingiReadyClassroomMathematicsK8withZearnMath": (
        "Supporting i-Ready Classroom Mathematics K8 with Zearn Math"
    ),
    "ZearnMathOverview[CoreComplement]": "Zearn Math Overview [Core Complement]",
    "Zearn_factsheet": "Zearn Factsheet",
    "ZearnenVisionK8Alignment": "Zearn enVision K8 Alignment",
    "accelerationmethodology": "AccelerationMethodology",
}

# Any .md / .pdf / .txt under documents/ is ingested (recursive). Skip crawl metadata.
SUPPORTED_SUFFIXES = {".md", ".pdf", ".txt"}
SKIP_FILENAMES = {"manifest.json", ".DS_Store"}

_pdf_manifest_cache: dict[Path, dict[str, str]] = {}


@dataclass
class IngestResult:
    document_id: str
    chunks_indexed: int
    status: str
    vectors_cleared: int = 0


@dataclass
class RetrievedChunk:
    text: str
    document_id: str
    title: str
    source_url: str
    source: str
    chunk_id: str = ""
    chunk_index: int = -1
    merged_chunk_ids: list[str] | None = None


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


def humanize_document_id(document_id: str) -> str:
    spaced = GLUED_CONNECTOR_RE.sub(r" \1 ", document_id)
    spaced = GRADE_RANGE_RE.sub(r"\1-\2", spaced)
    spaced = spaced.replace("_", " ").replace("-", " ")
    spaced = CAMEL_BOUNDARY_RE.sub(" ", spaced)
    return re.sub(r"\s+", " ", spaced).strip()


def humanize_pdf_document_id(document_id: str) -> str:
    """Filename → display title (without PDF suffix)."""
    override = PDF_TITLE_OVERRIDES.get(document_id)
    if override is not None:
        return override

    text = document_id
    # Bracketed segments: [CoreComplement] -> [Core Complement]
    def _humanize_bracket(match: re.Match[str]) -> str:
        inner = CAMEL_BOUNDARY_RE.sub(" ", match.group(1))
        inner = re.sub(r"\s+", " ", inner).strip()
        return f"[{inner}]"

    text = re.sub(r"\[([^\]]+)\]", _humanize_bracket, text)
    # Product names glued to neighbors in filenames
    for old, new in (
        ("SupportingenVision", "Supporting enVision"),
        ("ZearnenVision", "Zearn enVision"),
        ("Supportingi-Ready", "Supporting i-Ready"),
        ("SupportingiReady", "Supporting i-Ready"),
    ):
        text = text.replace(old, new)
    return humanize_document_id(text)


def resolve_pdf_document_title(document_id: str) -> str:
    """Title from the PDF filename, marked so readers know the source is a PDF."""
    name = humanize_pdf_document_id(document_id)
    if not name:
        return ""
    return f"{name} {PDF_TITLE_SUFFIX}"


def resolve_document_title(
    body: str,
    *,
    frontmatter: dict[str, str] | None = None,
    document_id: str = "",
) -> str:
    """Title from frontmatter `title`, first markdown H1, then humanized document_id."""
    if frontmatter:
        fm_title = frontmatter.get("title", "").strip()
        if fm_title:
            return fm_title

    for match in H1_RE.finditer(body):
        heading = match.group(1).strip()
        if heading:
            return heading

    if document_id:
        return humanize_document_id(document_id)
    return ""


def display_title_for_chunk(
    document_id: str,
    metadata_title: str = "",
) -> str:
    title = metadata_title.strip()
    if title and title != document_id:
        return title
    return humanize_document_id(document_id) if document_id else title


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
    title = resolve_document_title(body, frontmatter=frontmatter, document_id=document_id)
    metadata = {
        "document_id": document_id,
        "source": str(path.relative_to(DOCS_DIR)),
        "title": title,
        "source_url": frontmatter.get("source_url", ""),
    }
    return Document(page_content=body, metadata=metadata)


def _normalize_pdf_text(text: str) -> str:
    """Preserve PDF line structure for structure-aware chunking."""
    return soft_normalize_pdf_text(text)


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


def _load_pdf_manifest_urls(manifest_path: Path) -> dict[str, str]:
    """Map PDF filename → direct download URL from a crawl manifest."""
    if manifest_path in _pdf_manifest_cache:
        return _pdf_manifest_cache[manifest_path]

    urls: dict[str, str] = {}
    if not manifest_path.is_file():
        _pdf_manifest_cache[manifest_path] = urls
        return urls

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _pdf_manifest_cache[manifest_path] = urls
        return urls

    for entry in data.get("pdfs", []):
        filename = str(entry.get("filename", "")).strip()
        url = str(entry.get("url", "")).strip()
        if filename and url:
            urls[filename] = url

    _pdf_manifest_cache[manifest_path] = urls
    return urls


def _source_url_for_pdf(path: Path) -> str:
    """Resolve direct PDF URL from ``manifest.json`` in the same directory."""
    return _load_pdf_manifest_urls(path.parent / "manifest.json").get(path.name, "")


def _load_pdf(path: Path) -> list[Document]:
    """Load one Document per non-empty PDF page."""
    document_id = path.stem
    base_metadata = {
        "document_id": document_id,
        "source": str(path.relative_to(DOCS_DIR)),
        "title": resolve_pdf_document_title(document_id),
        "source_url": _source_url_for_pdf(path),
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


def _load_text(path: Path) -> Document | None:
    try:
        body = _strip_invisible_chars(path.read_text(encoding="utf-8"))
    except OSError:
        return None

    if not body.strip():
        return None

    return Document(
        page_content=body,
        metadata={
            "document_id": path.stem,
            "source": str(path.relative_to(DOCS_DIR)),
            "title": resolve_document_title(body, document_id=path.stem),
            "source_url": "",
        },
    )


def _load_document_file(path: Path) -> list[Document]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        doc = _load_markdown(path)
        return [doc] if doc is not None else []
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix == ".txt":
        doc = _load_text(path)
        return [doc] if doc is not None else []
    return []


def load_documents(root: Path | None = None) -> list[Document]:
    """Load all supported files under ``documents/`` (or ``root`` if provided)."""
    documents: list[Document] = []
    docs_root = (root or DOCS_DIR).resolve()
    if not docs_root.exists():
        return documents

    for path in sorted(docs_root.rglob("*")):
        if not path.is_file() or path.name in SKIP_FILENAMES:
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        documents.extend(_load_document_file(path))

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
    *,
    title: str = "",
    source_url: str = "",
) -> list[Document]:
    chunk_size, chunk_overlap = resolve_chunk_settings(chunk_size, chunk_overlap)
    splitter = _make_splitter(chunk_size, chunk_overlap)
    metadata: dict[str, str] = {"document_id": document_id, "source": source}
    if title:
        metadata["title"] = title
    if source_url:
        metadata["source_url"] = source_url
    doc = Document(page_content=text, metadata=metadata)
    return structure_chunk_document(doc, chunk_size, chunk_overlap, splitter)


def chunk_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    chunk_size, chunk_overlap = resolve_chunk_settings(chunk_size, chunk_overlap)
    splitter = _make_splitter(chunk_size, chunk_overlap)
    chunks: list[Document] = []
    for doc in documents:
        chunks.extend(structure_chunk_document(doc, chunk_size, chunk_overlap, splitter))
    return chunks


def _chunk_id(document_id: str, chunk_index: int) -> str:
    safe_id = str(document_id).replace("/", "_")
    return f"{safe_id}__chunk_{chunk_index}"


def _pinecone_document_filter(
    document_ids: list[str] | None = None,
    exclude_document_ids: list[str] | None = None,
) -> dict | None:
    """Build a Pinecone metadata filter. Include whitelist wins over exclude."""
    if document_ids:
        cleaned = [doc_id.strip() for doc_id in document_ids if doc_id.strip()]
        if not cleaned:
            return None
        if len(cleaned) == 1:
            return {"document_id": cleaned[0]}
        return {"document_id": {"$in": cleaned}}

    excluded = [doc_id.strip() for doc_id in (exclude_document_ids or []) if doc_id.strip()]
    if not excluded:
        return None
    if len(excluded) == 1:
        return {"document_id": {"$ne": excluded[0]}}
    return {"document_id": {"$nin": excluded}}


def excluded_document_ids_from_env() -> list[str]:
    """Default document_ids to omit from general retrieval (comma-separated env var)."""
    raw = os.getenv("EXCLUDE_DOCUMENT_IDS", "employee_handbook").strip()
    if not raw or raw.lower() in ("false", "none", "0"):
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def resolve_retrieval_filters(
    document_ids: list[str] | None,
    exclude_document_ids: list[str] | None = None,
) -> tuple[list[str] | None, list[str] | None]:
    """Apply include whitelist when set; otherwise apply exclude list (request or env default)."""
    include = document_ids or None
    if include:
        return include, None

    if exclude_document_ids is not None:
        exclude = exclude_document_ids or None
    else:
        exclude = excluded_document_ids_from_env() or None
    return None, exclude


@lru_cache(maxsize=1)
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


@lru_cache(maxsize=1)
def _embeddings_client() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=embedding_model())


def reset_clients() -> None:
    """Clear cached Pinecone/embeddings clients (e.g. after env changes in tests)."""
    _pinecone_index.cache_clear()
    _embeddings_client.cache_clear()


def _chunk_to_metadata(chunk: Document, chunk_index: int) -> dict[str, str | int]:
    metadata: dict[str, str | int] = {
        METADATA_TEXT_KEY: chunk.page_content[:35000],
        "document_id": str(chunk.metadata.get("document_id", "")),
        "chunk_index": chunk_index,
        "source": str(chunk.metadata.get("source", "")),
    }
    title = str(chunk.metadata.get("title", "")).strip()
    if title:
        metadata["title"] = title
    source_url = str(chunk.metadata.get("source_url", "")).strip()
    if source_url:
        metadata["source_url"] = source_url
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
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    replace_existing: bool = True,
    source: str | None = None,
) -> IngestResult:
    """Chunk, embed, and upsert a single pasted document."""
    chunk_size, chunk_overlap = resolve_chunk_settings(chunk_size, chunk_overlap)
    doc_id = document_id.strip()
    body = _strip_invisible_chars(text.strip())
    if not doc_id:
        raise ValueError("document_id must not be empty")
    if not body:
        raise ValueError("text must not be empty")

    doc_source = source or f"ui/{doc_id}"
    frontmatter: dict[str, str] = {}
    body_text = body
    if body.startswith("---"):
        frontmatter, body_text = _parse_markdown_frontmatter(body)
    title = resolve_document_title(body_text, frontmatter=frontmatter or None, document_id=doc_id)
    source_url = frontmatter.get("source_url", "") if frontmatter else ""
    chunks = chunk_text(
        body_text,
        doc_id,
        doc_source,
        chunk_size,
        chunk_overlap,
        title=title,
        source_url=source_url,
    )
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
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
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
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
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


def retrieve_chunks(
    question: str,
    k: int = 3,
    document_ids: list[str] | None = None,
    exclude_document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    embeddings = _embeddings_client()
    index = _pinecone_index()

    query_vector = embeddings.embed_query(question)
    query_kwargs: dict = {
        "vector": query_vector,
        "top_k": k,
        "include_metadata": True,
    }
    metadata_filter = _pinecone_document_filter(document_ids, exclude_document_ids)
    if metadata_filter:
        query_kwargs["filter"] = metadata_filter

    results = index.query(**query_kwargs)

    return [_match_to_retrieved_chunk(match) for match in results.get("matches", [])]


def _retrieved_chunk_from_metadata(metadata: dict, *, chunk_id: str) -> RetrievedChunk:
    document_id = str(metadata.get("document_id", ""))
    chunk_index_raw = metadata.get("chunk_index", -1)
    chunk_index = int(chunk_index_raw) if chunk_index_raw is not None else -1
    return RetrievedChunk(
        text=str(metadata.get(METADATA_TEXT_KEY, "")),
        document_id=document_id,
        title=display_title_for_chunk(document_id, str(metadata.get("title", ""))),
        source_url=str(metadata.get("source_url", "")),
        source=str(metadata.get("source", "")),
        chunk_id=chunk_id,
        chunk_index=chunk_index,
    )


def _match_to_retrieved_chunk(match: dict) -> RetrievedChunk:
    metadata = match.get("metadata") or {}
    document_id = str(metadata.get("document_id", ""))
    chunk_index_raw = metadata.get("chunk_index", -1)
    chunk_index = int(chunk_index_raw) if chunk_index_raw is not None else -1
    chunk_id = str(match.get("id") or _chunk_id(document_id, chunk_index))
    return _retrieved_chunk_from_metadata(metadata, chunk_id=chunk_id)


def retrieve_chunks_bm25(
    question: str,
    k: int = 3,
    document_ids: list[str] | None = None,
    exclude_document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    bm25_index = ensure_bm25_ready()
    chunks: list[RetrievedChunk] = []

    for chunk_id, _score in bm25_index.search(
        question,
        k=k,
        document_ids=document_ids,
        exclude_document_ids=exclude_document_ids,
    ):
        record = bm25_index.get_record(chunk_id)
        if record is None:
            continue
        chunks.append(
            RetrievedChunk(
                text=record.text,
                document_id=record.document_id,
                title=display_title_for_chunk(record.document_id, record.title),
                source_url=record.source_url,
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


def apply_diverse_filter(
    candidates: list[RetrievedChunk],
    k: int,
    max_per_document: int,
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    per_document: dict[str, int] = {}
    for chunk in candidates:
        doc_id = chunk.document_id or chunk.source
        if per_document.get(doc_id, 0) >= max_per_document:
            continue
        selected.append(chunk)
        per_document[doc_id] = per_document.get(doc_id, 0) + 1
        if len(selected) >= k:
            break
    return selected


def _record_to_retrieved_chunk(record) -> RetrievedChunk:
    return RetrievedChunk(
        text=record.text,
        document_id=record.document_id,
        title=display_title_for_chunk(record.document_id, record.title),
        source_url=record.source_url,
        source=record.source,
        chunk_id=record.chunk_id,
        chunk_index=record.chunk_index,
    )


def lookup_chunk_by_id(chunk_id: str) -> RetrievedChunk | None:
    """Resolve a chunk by id from the in-process BM25 index, then Pinecone."""
    record = get_bm25_index().get_record(chunk_id)
    if record is not None:
        return _record_to_retrieved_chunk(record)

    index = _pinecone_index()
    fetched = index.fetch(ids=[chunk_id])
    vector = (fetched.vectors or {}).get(chunk_id)
    if vector is None:
        return None

    metadata = vector.metadata or {}
    return _retrieved_chunk_from_metadata(metadata, chunk_id=chunk_id)


def lookup_chunks_by_ids(chunk_ids: list[str]) -> dict[str, RetrievedChunk]:
    """Resolve many chunks by id: in-memory BM25 first, then one batched Pinecone fetch for misses."""
    resolved: dict[str, RetrievedChunk] = {}
    if not chunk_ids:
        return resolved

    unique_ids = list(dict.fromkeys(chunk_ids))
    bm25 = get_bm25_index()
    misses: list[str] = []
    for chunk_id in unique_ids:
        record = bm25.get_record(chunk_id)
        if record is not None:
            resolved[chunk_id] = _record_to_retrieved_chunk(record)
        else:
            misses.append(chunk_id)

    if misses:
        index = _pinecone_index()
        for start in range(0, len(misses), UPSERT_BATCH_SIZE):
            batch = misses[start : start + UPSERT_BATCH_SIZE]
            fetched = index.fetch(ids=batch)
            for chunk_id, vector in (fetched.vectors or {}).items():
                metadata = vector.metadata or {}
                resolved[chunk_id] = _retrieved_chunk_from_metadata(metadata, chunk_id=chunk_id)

    return resolved


def _neighbor_ids_for_hit(hit: RetrievedChunk, radius: int) -> list[str]:
    """Neighbor chunk ids for a hit, ordered by increasing distance (closest first)."""
    if radius <= 0 or hit.chunk_index < 0 or not hit.document_id:
        return []

    ids: list[str] = []
    for offset in sorted(range(-radius, radius + 1), key=lambda value: abs(value)):
        if offset == 0:
            continue
        neighbor_index = hit.chunk_index + offset
        if neighbor_index < 0:
            continue
        ids.append(_chunk_id(hit.document_id, neighbor_index))
    return ids


def _prefetch_neighbors(hits: list[RetrievedChunk], radius: int) -> dict[str, RetrievedChunk]:
    """Resolve every neighbor chunk needed across all hits in one batched lookup."""
    needed: list[str] = []
    for hit in hits:
        needed.extend(_neighbor_ids_for_hit(hit, radius))
    return lookup_chunks_by_ids(needed)


def _group_hit_with_neighbors(
    hit: RetrievedChunk, radius: int, neighbor_map: dict[str, RetrievedChunk]
) -> list[RetrievedChunk]:
    group = [hit]
    seen = {hit.chunk_id}

    for neighbor_id in _neighbor_ids_for_hit(hit, radius):
        if neighbor_id in seen:
            continue
        neighbor = neighbor_map.get(neighbor_id)
        if neighbor is None or not neighbor.text.strip():
            continue
        group.append(neighbor)
        seen.add(neighbor_id)

    return group


def merge_neighbor_chunks(hits: list[RetrievedChunk], *, radius: int) -> list[RetrievedChunk]:
    """Combine each hit with chunk_index ± radius into one block for the LLM."""
    if radius <= 0 or not hits:
        return hits

    neighbor_map = _prefetch_neighbors(hits, radius)
    merged: list[RetrievedChunk] = []
    for hit in hits:
        group = _group_hit_with_neighbors(hit, radius, neighbor_map)
        group.sort(key=lambda chunk: chunk.chunk_index if chunk.chunk_index >= 0 else 0)

        texts: list[str] = []
        seen_text: set[str] = set()
        for chunk in group:
            text = chunk.text.strip()
            if text and text not in seen_text:
                texts.append(text)
                seen_text.add(text)

        chunk_ids = [chunk.chunk_id for chunk in group]
        indices = [chunk.chunk_index for chunk in group if chunk.chunk_index >= 0]
        merged.append(
            RetrievedChunk(
                text="\n\n".join(texts),
                document_id=hit.document_id,
                title=hit.title,
                source_url=hit.source_url,
                source=hit.source,
                chunk_id=hit.chunk_id,
                chunk_index=min(indices) if indices else hit.chunk_index,
                merged_chunk_ids=chunk_ids,
            )
        )

    return merged


def cap_context_chunks(chunks: list[RetrievedChunk], max_chunks: int) -> list[RetrievedChunk]:
    if max_chunks <= 0 or len(chunks) <= max_chunks:
        return chunks
    return chunks[:max_chunks]


def prepare_context_chunks(
    hits: list[RetrievedChunk],
    *,
    radius: int,
    expand_neighbors: bool,
    merge_neighbors: bool,
    max_chunks: int | None,
) -> list[RetrievedChunk]:
    """Neighbor expand/merge and optional cap — applied after diverse filter."""
    if not hits:
        return hits

    if expand_neighbors and radius > 0:
        if merge_neighbors:
            chunks = merge_neighbor_chunks(hits, radius=radius)
        else:
            chunks = expand_neighbor_chunks(hits, radius=radius)
    else:
        chunks = list(hits)

    if max_chunks is not None:
        chunks = cap_context_chunks(chunks, max_chunks)
    return chunks


def chunk_ids_for_context(chunks: list[RetrievedChunk]) -> list[str]:
    """Flatten chunk ids for API/eval (includes merged neighbor ids)."""
    ids: list[str] = []
    for chunk in chunks:
        if chunk.merged_chunk_ids:
            ids.extend(chunk.merged_chunk_ids)
        elif chunk.chunk_id:
            ids.append(chunk.chunk_id)
    return ids


def expand_neighbor_chunks(chunks: list[RetrievedChunk], *, radius: int) -> list[RetrievedChunk]:
    """Append adjacent chunks (same document_id) for each retrieved hit."""
    if radius <= 0 or not chunks:
        return chunks

    neighbor_map = _prefetch_neighbors(chunks, radius)
    expanded: list[RetrievedChunk] = []
    seen: set[str] = set()

    for chunk in chunks:
        if chunk.chunk_id not in seen:
            expanded.append(chunk)
            seen.add(chunk.chunk_id)

        for neighbor_id in _neighbor_ids_for_hit(chunk, radius):
            if neighbor_id in seen:
                continue
            neighbor = neighbor_map.get(neighbor_id)
            if neighbor is None or not neighbor.text.strip():
                continue
            expanded.append(neighbor)
            seen.add(neighbor_id)

    return expanded


def retrieve_chunks_hybrid(
    question: str,
    k: int = 6,
    fetch_k: int = 12,
    max_per_document: int = 2,
    document_ids: list[str] | None = None,
    exclude_document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Combine dense Pinecone search with BM25 via reciprocal rank fusion."""

    fetch_k = max(fetch_k, k)
    dense_candidates = retrieve_chunks(
        question, k=fetch_k, document_ids=document_ids, exclude_document_ids=exclude_document_ids
    )
    bm25_candidates = retrieve_chunks_bm25(
        question, k=fetch_k, document_ids=document_ids, exclude_document_ids=exclude_document_ids
    )
    fused_candidates = reciprocal_rank_fusion(dense_candidates, bm25_candidates)
    return apply_diverse_filter(fused_candidates, k=k, max_per_document=max_per_document)


def retrieve_chunks_diverse(
    question: str,
    k: int = 6,
    fetch_k: int = 12,
    max_per_document: int = 2,
    document_ids: list[str] | None = None,
    exclude_document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Retrieve top chunks while limiting how many come from the same document.

    Fetches more candidates than k, then keeps the highest-scoring chunks subject
    to a per-document cap so one long PDF does not dominate the context window.
    """
    fetch_k = max(fetch_k, k)
    candidates = retrieve_chunks(
        question, k=fetch_k, document_ids=document_ids, exclude_document_ids=exclude_document_ids
    )
    return apply_diverse_filter(candidates, k=k, max_per_document=max_per_document)


def debug_retrieve(
    question: str,
    k: int = 5,
    exclude_document_ids: list[str] | None = None,
) -> list[DebugRetrievedChunk]:
    """Embed a question and return top-k Pinecone matches with scores — no LLM."""

    embeddings = _embeddings_client()
    index = _pinecone_index()

    query_vector = embeddings.embed_query(question)
    query_kwargs: dict = {
        "vector": query_vector,
        "top_k": k,
        "include_metadata": True,
    }
    metadata_filter = _pinecone_document_filter(None, exclude_document_ids)
    if metadata_filter:
        query_kwargs["filter"] = metadata_filter

    results = index.query(**query_kwargs)

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
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                source=chunk.source,
                text=chunk.text,
                chunk_id=chunk.chunk_id,
                rank=rank,
            )
        )
    return debug_chunks


def debug_retrieve_hybrid(
    question: str,
    k: int = 5,
    exclude_document_ids: list[str] | None = None,
) -> HybridDebugResult:
    """Return dense, BM25, and fused rankings side-by-side for debugging."""

    dense_chunks = retrieve_chunks(question, k=k, exclude_document_ids=exclude_document_ids)
    bm25_raw = get_bm25_index().search(
        question, k=k, exclude_document_ids=exclude_document_ids
    )
    bm25_chunks = retrieve_chunks_bm25(
        question, k=k, exclude_document_ids=exclude_document_ids
    )
    bm25_scores = [score for _chunk_id, score in bm25_raw]
    fused_chunks = reciprocal_rank_fusion(
        retrieve_chunks(question, k=max(k, 10), exclude_document_ids=exclude_document_ids),
        retrieve_chunks_bm25(
            question, k=max(k, 10), exclude_document_ids=exclude_document_ids
        ),
    )[:k]

    return HybridDebugResult(
        dense=_retrieved_to_debug(dense_chunks),
        bm25=_retrieved_to_debug(bm25_chunks, bm25_scores),
        fused=_retrieved_to_debug(fused_chunks),
    )

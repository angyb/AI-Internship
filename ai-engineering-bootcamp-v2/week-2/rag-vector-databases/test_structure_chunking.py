"""Tests for structure-aware chunking."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingest import DOCS_DIR, _load_markdown, _load_pdf, chunk_documents
from structure_chunking import (
    pack_units,
    soft_normalize_pdf_text,
    split_into_units,
    structure_chunk_document,
)
from langchain_core.documents import Document


def _splitter(chunk_size: int = 500, chunk_overlap: int = 80) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def test_soft_normalize_preserves_newlines() -> None:
    raw = "Line one  \n\nLine two\t\textra"
    normalized = soft_normalize_pdf_text(raw)
    assert "\n" in normalized
    assert "Line one" in normalized
    assert "Line two extra" in normalized


def test_envision_grade4_topic5_in_one_chunk() -> None:
    pages = _load_pdf(DOCS_DIR / "zendesk/pdf/ZearnenVisionK8Alignment.pdf")
    chunks = chunk_documents(pages, chunk_size=500, chunk_overlap=80)

    topic5_chunks = [
        chunk
        for chunk in chunks
        if "Topic 5" in chunk.page_content
        and "Divide by 1-Digit Numbers" in chunk.page_content
    ]
    assert topic5_chunks, "expected a chunk containing Grade 4 Topic 5 row"

    match = topic5_chunks[0].page_content
    assert "Grade 4 Learning progression" in match
    assert "enVision Grade 4 Topic 5" in match
    assert "Mission 3" in match
    assert "continue working through" in match.lower()


def test_markdown_doc_still_chunks_sensibly() -> None:
    doc = _load_markdown(DOCS_DIR / "zendesk/md/add-a-co-teacher.md")
    assert doc is not None
    chunks = chunk_documents([doc], chunk_size=500, chunk_overlap=80)
    assert chunks
    combined = " ".join(chunk.page_content for chunk in chunks)
    assert "co-teacher" in combined.lower()
    assert "Roster" in combined


def test_pack_units_respects_chunk_size() -> None:
    units = ["alpha " * 40, "beta " * 40, "gamma " * 40]
    packed = pack_units(units, chunk_size=120, chunk_overlap=20, splitter=_splitter(120, 20))
    assert packed
    assert all(len(chunk) <= 120 for chunk in packed)


def test_pack_units_overlap_seed_respects_chunk_size() -> None:
    units = ["a" * 50, "b" * 50, "c" * 90]
    packed = pack_units(units, chunk_size=100, chunk_overlap=30, splitter=_splitter(100, 30))
    assert packed
    assert all(len(chunk) <= 100 for chunk in packed)


def test_split_into_units_detects_topic_rows() -> None:
    sample = (
        "Grade 4 Learning progression\n\n"
        "Topic 1: First topic (5 lessons) Mission 1: First mission (10 lessons)\n"
        "Topic 2: Second topic (6 lessons) Note: continue Mission 1."
    )
    units = split_into_units(sample, "pdf")
    assert any("Topic 1:" in unit for unit in units)
    assert any("Topic 2:" in unit for unit in units)


def test_short_document_kept_whole() -> None:
    doc = Document(
        page_content="Short help article about rostering.",
        metadata={"document_id": "short", "source": "zendesk/md/short.md"},
    )
    chunks = structure_chunk_document(doc, 500, 80, _splitter())
    assert len(chunks) == 1
    assert chunks[0].page_content == doc.page_content


def test_short_structural_document_gets_enrichment() -> None:
    doc = Document(
        page_content=(
            "Grade 4 Learning progression\n"
            "Topic 5: Divide by 1-Digit Numbers (10 lessons)\n"
            "Note: continue working through Zearn Mission 3"
        ),
        metadata={"document_id": "align", "source": "zendesk/pdf/align.pdf", "page_number": 1},
    )
    chunks = structure_chunk_document(doc, 500, 80, _splitter())
    assert len(chunks) == 1
    assert "enVision Grade 4 Topic 5" in chunks[0].page_content

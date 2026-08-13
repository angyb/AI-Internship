"""Structure-aware chunking: preserve PDF rows/sections instead of blind character splits."""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

INVISIBLE_CHAR_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060]")
HORIZONTAL_WS_RE = re.compile(r"[^\S\n]+")

SECTION_HEADER_RE = re.compile(
    r"(Grade \d+ Learning progression|Supporting [^\n|]{8,120}(?:K-\d+|K-8))",
    re.IGNORECASE,
)

ROW_START_RE = re.compile(
    r"(?:^|[\n.]\s*)("
    r"Topic \d+:"
    r"|Unit \d+:"
    r"|Mission \d+, Topic [A-Z]"
    r"|Mission \d+:"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6}\s+.+)$", re.MULTILINE)

STRUCTURAL_SIGNAL_RE = re.compile(
    r"Grade \d+ Learning progression|Topic \d+:|Unit \d+:|Mission \d+:",
    re.IGNORECASE,
)

GRADE_SECTION_RE = re.compile(r"Grade (\d+) Learning progression", re.IGNORECASE)

SourceType = Literal["pdf", "markdown", "text"]


def soft_normalize_pdf_text(text: str) -> str:
    """Strip invisible chars, collapse horizontal whitespace, preserve line breaks."""
    text = INVISIBLE_CHAR_RE.sub("", text)
    lines = [HORIZONTAL_WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    normalized = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()


def _source_type_for_document(doc: Document) -> SourceType:
    if "page_number" in doc.metadata:
        return "pdf"
    source = str(doc.metadata.get("source", "")).lower()
    if source.endswith(".md"):
        return "markdown"
    return "text"


def _split_markdown_sections(text: str) -> list[str]:
    """Split on markdown headings; each unit includes its heading line."""
    matches = list(MARKDOWN_HEADING_RE.finditer(text))
    if not matches:
        return _split_paragraph_units(text)

    units: list[str] = []
    if matches[0].start() > 0:
        prefix = text[: matches[0].start()].strip()
        if prefix:
            units.extend(_split_paragraph_units(prefix))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        if section:
            units.append(section)
    return units


def _split_paragraph_units(text: str) -> list[str]:
    parts = re.split(r"\n\n+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _split_structural_rows(text: str) -> list[str]:
    """Split alignment-like text at section headers and Topic/Mission row boundaries."""
    markers: list[tuple[int, int]] = []
    for pattern in (SECTION_HEADER_RE, ROW_START_RE):
        for match in pattern.finditer(text):
            start = match.start(1) if match.lastindex else match.start()
            markers.append((start, match.end()))

    if not markers:
        return [text.strip()] if text.strip() else []

    markers.sort(key=lambda item: item[0])
    deduped: list[tuple[int, int]] = []
    last_start = -1
    for start, end in markers:
        if start <= last_start:
            continue
        deduped.append((start, end))
        last_start = start

    units: list[str] = []
    cursor = 0
    for start, _end in deduped:
        if start > cursor:
            prefix = text[cursor:start].strip(" .\n")
            if prefix:
                units.append(prefix)
        cursor = start

    tail = text[cursor:].strip()
    if tail:
        units.append(tail)

    if not units:
        return [text.strip()] if text.strip() else []
    return units


def _split_multi_topic_units(units: list[str]) -> list[str]:
    """Split packed alignment text so each Topic/Unit row can become its own chunk."""
    topic_boundary = re.compile(r"(?=Topic \d+:|Unit \d+:)", re.IGNORECASE)
    split_units: list[str] = []
    for unit in units:
        matches = list(topic_boundary.finditer(unit))
        if len(matches) <= 1:
            split_units.append(unit)
            continue
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(unit)
            piece = unit[start:end].strip(" .\n")
            if piece:
                split_units.append(piece)
    return split_units


def coalesce_section_intro_units(units: list[str]) -> list[str]:
    """Merge grade intro boilerplate with the following row so intros are not standalone chunks."""
    if not units:
        return []

    merged: list[str] = []
    index = 0
    while index < len(units):
        unit = units[index]
        next_unit = units[index + 1] if index + 1 < len(units) else ""
        intro_only = SECTION_HEADER_RE.search(unit) and not ROW_START_RE.search(unit)
        if intro_only and next_unit:
            merged.append(f"{unit.strip()} {next_unit.strip()}".strip())
            index += 2
            continue
        merged.append(unit)
        index += 1
    return merged


def split_into_units(text: str, source_type: SourceType) -> list[str]:
    """Produce ordered atomic strings (paragraphs, sections, or table rows)."""
    text = text.strip()
    if not text:
        return []

    if source_type == "markdown":
        base_units = _split_markdown_sections(text)
    else:
        base_units = _split_paragraph_units(text)

    units = []
    for unit in base_units:
        if STRUCTURAL_SIGNAL_RE.search(unit) and ROW_START_RE.search(unit):
            units.extend(_split_structural_rows(unit))
        else:
            units.append(unit)

    units = coalesce_section_intro_units(units)
    units = _split_multi_topic_units(units)
    units = prefix_units_with_section(units)
    return [unit for unit in units if unit.strip()]


def _contains_row_marker(text: str) -> bool:
    return bool(re.search(r"Topic \d+:|Unit \d+:|Mission \d+:", text, re.IGNORECASE))


def enrich_alignment_row_unit(section: str, unit: str) -> str:
    """Add enVision Grade N Topic M (and Zearn Mission) labels for retrieval matching."""
    grade_m = GRADE_SECTION_RE.search(section)
    topic_m = re.search(r"Topic (\d+):", unit, re.IGNORECASE)
    if not (grade_m and topic_m):
        return unit

    grade = grade_m.group(1)
    topic = topic_m.group(1)
    label = f"enVision Grade {grade} Topic {topic}"
    if label.lower() in unit.lower():
        return unit

    mission_m = re.search(r"Zearn Mission (\d+)", unit, re.IGNORECASE)
    if mission_m:
        label = f"{label} Zearn Mission {mission_m.group(1)}"
    return f"{label} | {unit}"


def prefix_units_with_section(units: list[str]) -> list[str]:
    """Attach the active grade section label to each Topic/Unit row unit."""
    section = ""
    prefixed: list[str] = []
    for unit in units:
        grade_match = GRADE_SECTION_RE.search(unit)
        if grade_match:
            section = f"Grade {grade_match.group(1)} Learning progression"

        row_unit = unit
        if section and _contains_row_marker(unit) and section.lower() not in unit.lower():
            row_unit = f"{section} | {unit}"

        if section and _contains_row_marker(row_unit):
            row_unit = enrich_alignment_row_unit(section, row_unit)

        prefixed.append(row_unit)
    return prefixed


def has_structural_content(text: str, units: list[str]) -> bool:
    if STRUCTURAL_SIGNAL_RE.search(text):
        return True
    if len(units) > 1 and any(ROW_START_RE.search(unit) for unit in units):
        return True
    return False


def _is_topic_row_unit(unit: str) -> bool:
    stripped = unit.strip()
    return bool(re.match(r"(Grade \d+ Learning progression \| )?(Topic \d+:|Unit \d+:)", stripped, re.I))


def pack_units(
    units: list[str],
    chunk_size: int,
    chunk_overlap: int,
    splitter: RecursiveCharacterTextSplitter,
) -> list[str]:
    """Pack atomic units into chunks without splitting units (unless a unit exceeds chunk_size)."""
    if not units:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    separator = " "

    def joined(parts: list[str]) -> str:
        return separator.join(parts)

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append(joined(current))
            current = []
            current_len = 0

    for unit in units:
        unit = unit.strip()
        if not unit:
            continue

        if len(unit) > chunk_size:
            flush()
            chunks.extend(splitter.split_text(unit))
            continue

        if current and _is_topic_row_unit(unit) and any(_is_topic_row_unit(p) for p in current):
            flush()

        extra = len(separator) if current else 0
        if current and current_len + extra + len(unit) > chunk_size:
            chunks.append(joined(current))
            seed: list[str] = []
            seed_len = 0
            for piece in reversed(current):
                piece_extra = len(separator) if seed else 0
                if seed_len + piece_extra + len(piece) > chunk_overlap:
                    break
                seed.insert(0, piece)
                seed_len += piece_extra + len(piece)
            current = seed + [unit]
            current_len = len(joined(current))
            if current_len > chunk_size:
                current = [unit]
                current_len = len(unit)
        else:
            current.append(unit)
            current_len += extra + len(unit)

    flush()
    return chunks


def prefix_section_context(chunks: list[str]) -> list[str]:
    """Ensure grade section labels appear on row chunks after unit packing."""
    section = ""
    prefixed: list[str] = []

    for chunk in chunks:
        grade_match = GRADE_SECTION_RE.search(chunk)
        if grade_match:
            section = f"Grade {grade_match.group(1)} Learning progression"

        row_chunk = chunk
        if section and _contains_row_marker(chunk) and section.lower() not in chunk.lower():
            row_chunk = f"{section} | {chunk}"

        if section and _contains_row_marker(row_chunk):
            row_chunk = enrich_alignment_row_unit(section, row_chunk)

        prefixed.append(row_chunk)

    return prefixed


def structure_chunk_document(
    doc: Document,
    chunk_size: int,
    chunk_overlap: int,
    splitter: RecursiveCharacterTextSplitter,
) -> list[Document]:
    """Chunk one document using structure-aware packing with character-split fallback."""
    text = doc.page_content.strip()
    if not text:
        return []

    source_type = _source_type_for_document(doc)
    units = split_into_units(text, source_type)

    if not has_structural_content(text, units):
        if len(text) <= chunk_size:
            return [doc]
        return splitter.split_documents([doc])

    packed = pack_units(units, chunk_size, chunk_overlap, splitter)
    if not packed:
        return splitter.split_documents([doc])

    final_texts = prefix_section_context(packed)
    metadata = dict(doc.metadata)
    return [Document(page_content=chunk_text, metadata=metadata) for chunk_text in final_texts]


def structure_chunk_documents(
    documents: list[Document],
    chunk_size: int,
    chunk_overlap: int,
    splitter: RecursiveCharacterTextSplitter,
) -> list[Document]:
    chunks: list[Document] = []
    for doc in documents:
        chunks.extend(structure_chunk_document(doc, chunk_size, chunk_overlap, splitter))
    return chunks

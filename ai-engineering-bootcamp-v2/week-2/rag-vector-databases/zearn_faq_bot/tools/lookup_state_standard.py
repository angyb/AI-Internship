"""lookup_state_standard — exact state standards → Zearn lesson/topic lookup."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

from pypdf import PdfReader

DOCS_DIR = Path(__file__).resolve().parents[3] / "documents"
STANDARDS_PDF_DIR = DOCS_DIR / "website" / "pdf"
STANDARDS_PREFIX = "ZearnStateStandards_"

STANDARD_CODE_RE = re.compile(
    r"^(?:K|\d+)\.[A-Z0-9]+(?:\.[A-Z0-9]+)*$",
    re.IGNORECASE,
)
NOISE_LINE_RE = re.compile(
    r"^(?:©|\d{1,3}$|.*\bSTANDARDS\b.*$)",
    re.IGNORECASE,
)
MISSION_LINE_RE = re.compile(r"^Mission\s+\d+", re.IGNORECASE)


def _normalize_standard_code(code: str) -> str:
    return re.sub(r"\s+", "", code.strip()).upper()


def _normalize_state_key(state: str) -> str:
    return re.sub(r"[\s\-]+", "_", state.strip().lower())


@lru_cache(maxsize=1)
def _state_pdf_index() -> dict[str, Path]:
    """Map normalized state key → standards PDF path."""
    index: dict[str, Path] = {}
    for path in sorted(STANDARDS_PDF_DIR.glob(f"{STANDARDS_PREFIX}*.pdf")):
        state_part = path.stem[len(STANDARDS_PREFIX) :]
        index[_normalize_state_key(state_part.replace("_", " "))] = path
        index[_normalize_state_key(state_part)] = path
    return index


def _resolve_state_pdf(state: str) -> tuple[Path | None, str | None]:
    key = _normalize_state_key(state)
    index = _state_pdf_index()
    path = index.get(key)
    if path is not None:
        return path, None

    available = sorted(
        {
            p.stem[len(STANDARDS_PREFIX) :].replace("_", " ")
            for p in STANDARDS_PDF_DIR.glob(f"{STANDARDS_PREFIX}*.pdf")
        }
    )
    return None, (
        f"Unknown state {state!r}. Available states include: "
        + ", ".join(available[:10])
        + ("..." if len(available) > 10 else "")
    )


def _extract_pdf_text(path: Path) -> str:
    if fitz is not None:
        try:
            with fitz.open(str(path)) as pdf:
                return "\n".join(page.get_text() for page in pdf)
        except OSError:
            pass

    try:
        reader = PdfReader(str(path))
    except OSError as exc:
        raise RuntimeError(f"Could not read PDF: {path.name}") from exc

    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _load_pdf_meta(path: Path) -> tuple[str, str]:
    document_id = path.stem
    title = document_id.replace("_", " ").replace("ZearnStateStandards", "Zearn State Standards")
    source_url = ""
    manifest_path = path.parent / "manifest.json"
    if manifest_path.is_file():
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entries = []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("filename") == path.name:
                    source_url = str(entry.get("url", "")).strip()
                    break
    if not title.startswith("Zearn State Standards"):
        title = f"Zearn State Standards {path.stem[len(STANDARDS_PREFIX):].replace('_', ' ')}"
    return title, source_url


def _is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if NOISE_LINE_RE.match(stripped):
        return True
    if stripped.startswith("http"):
        return True
    return False


def _parse_standards_from_text(text: str) -> dict[str, dict[str, object]]:
    """Parse all standard entries from one state standards PDF."""
    entries: dict[str, dict[str, object]] = {}
    current_code: str | None = None
    description_lines: list[str] = []
    mappings: list[str] = []

    def flush() -> None:
        nonlocal current_code, description_lines, mappings
        if current_code is None:
            return
        entries[current_code] = {
            "description": " ".join(description_lines).strip(),
            "zearn_mappings": list(mappings),
        }
        current_code = None
        description_lines = []
        mappings = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if STANDARD_CODE_RE.match(line):
            flush()
            current_code = _normalize_standard_code(line)
            continue

        if current_code is None or _is_noise_line(line):
            continue

        if MISSION_LINE_RE.match(line):
            mappings.append(line)
        elif not mappings:
            description_lines.append(line)

    flush()
    return entries


@lru_cache(maxsize=64)
def _standards_for_pdf(pdf_path_str: str) -> dict[str, dict[str, object]]:
    return _parse_standards_from_text(_extract_pdf_text(Path(pdf_path_str)))


def _domain_prefix(code: str) -> str:
    """Return grade.domain prefix, e.g. 3.OA.A.5 → 3.OA, K.CC.1 → K.CC."""
    parts = code.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return parts[0]


def _similar_codes(requested: str, all_codes: list[str], *, limit: int = 8) -> list[str]:
    prefix = _domain_prefix(requested)
    matches = [code for code in sorted(all_codes) if code.startswith(prefix + ".") or code == prefix]
    if requested in matches:
        matches.remove(requested)
    return matches[:limit]


def lookup_state_standard(state: str, standard_code: str) -> dict:
    """Look up a state standard code in that state's Zearn standards PDF.

    Use this when the user asks which Zearn lessons or topics cover a specific
    state standard (e.g. "3.OA.5 in Kansas"). Performs exact code matching
    against the state PDF only — never guesses across states.

    Args:
        state: U.S. state name (e.g. "Kansas", "New York").
        standard_code: Standard code exactly as the user stated (e.g. "3.OA.A.5").

    Returns:
        Dict with found (bool), requested_code, state, description, zearn_mappings,
        title, source_url, similar_codes_in_state (when not found), and message.
    """
    requested = _normalize_standard_code(standard_code)
    pdf_path, state_error = _resolve_state_pdf(state)
    if pdf_path is None:
        return {
            "found": False,
            "state": state,
            "requested_code": requested,
            "error": state_error,
            "zearn_mappings": [],
            "similar_codes_in_state": [],
        }

    title, source_url = _load_pdf_meta(pdf_path)
    try:
        entries = _standards_for_pdf(str(pdf_path))
    except RuntimeError as exc:
        return {
            "found": False,
            "state": state,
            "requested_code": requested,
            "error": str(exc),
            "title": title,
            "source_url": source_url,
            "zearn_mappings": [],
            "similar_codes_in_state": [],
        }

    all_codes = sorted(entries.keys())
    if requested in entries:
        entry = entries[requested]
        mappings = entry.get("zearn_mappings") or []
        return {
            "found": True,
            "state": state,
            "requested_code": requested,
            "matched_code": requested,
            "description": entry.get("description", ""),
            "zearn_mappings": list(mappings),
            "title": title,
            "source_url": source_url,
            "similar_codes_in_state": [],
            "message": (
                f"Exact match for {requested} in {state}. "
                "List only zearn_mappings from this result."
            ),
        }

    similar = _similar_codes(requested, all_codes)
    return {
        "found": False,
        "state": state,
        "requested_code": requested,
        "description": "",
        "zearn_mappings": [],
        "title": title,
        "source_url": source_url,
        "similar_codes_in_state": similar,
        "message": (
            f"{requested} was not found in the {state} Zearn standards PDF. "
            "Do not list Zearn lessons or topics unless found is true. "
            "You may suggest codes from similar_codes_in_state if relevant."
        ),
    }

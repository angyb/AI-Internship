#!/usr/bin/env python3
"""Compare local website/md files against live about.zearn.org pages."""

from __future__ import annotations

import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests
import yaml

from extract import USER_AGENT, process_page_html

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "documents" / "website" / "md"
REQUEST_DELAY_SEC = 0.35

INVISIBLE_CHAR_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060]")
ESCAPED_NUMBER_RE = re.compile(r"^\d+\\\.")
GLUED_PATTERNS = (
    "canreview",
    "rolepromoted",
    "orClasslink",
    "throughClever",
    "ofIndependent",
    "andLesson",
    "havecreated",
    "easier celebrate",
    "sign up for a and",
    "access to so that",
    "websiteor",
    "aZearn",
    "ourZearn",
)


def parse_markdown_file(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw.strip()
    parts = raw.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    return meta, parts[2].strip()


def strip_leading_h1(body: str) -> str:
    return re.sub(r"^#\s+[^\n]+\n+", "", body, count=1)


def normalize(text: str) -> str:
    text = INVISIBLE_CHAR_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def first_diff_excerpt(local: str, live: str, width: int = 140) -> tuple[str, str] | None:
    sm = SequenceMatcher(None, local, live)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        return local[max(0, i1 - 30) : i2 + 30][:width], live[max(0, j1 - 30) : j2 + 30][:width]
    return None


def find_issues(local: str, live: str) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []

    for pattern in GLUED_PATTERNS:
        if pattern in local and pattern not in live:
            issues.append(("glued_or_typo", pattern))

    for match in re.finditer(r"[a-z]{2,}[A-Z][a-zA-Z]+", local):
        span = match.group(0)
        if span in live:
            continue
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", span)
        if spaced in live:
            issues.append(("glued_or_typo", span))

    if ESCAPED_NUMBER_RE.search(local) and not ESCAPED_NUMBER_RE.search(live):
        issues.append(("escaped_number", str(len(ESCAPED_NUMBER_RE.findall(local)))))

    if INVISIBLE_CHAR_RE.search(local):
        issues.append(("invisible_char", "yes"))

    if local == live:
        return issues

    # Live has a substantial sentence missing locally.
    for chunk in re.split(r"(?<=[.!?])\s+", live):
        chunk = chunk.strip()
        if len(chunk) < 40:
            continue
        if chunk not in local and chunk[:50] not in local:
            plain = re.sub(r"[#*\[\]]", "", chunk)
            if plain[:35] in local:
                continue
            issues.append(("missing_on_local", chunk[:80]))
            break

    return issues


def fetch_live_body(session: requests.Session, url: str) -> tuple[str | None, str | None]:
    try:
        response = session.get(url, timeout=45)
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, str(exc)

    file_content, _manifest, error = process_page_html(
        response.text, url, lastmod=None, extraction_method="compare_live"
    )
    if error or not file_content:
        return None, error or "extraction failed"

    _, body = parse_markdown_file(file_content)
    return strip_leading_h1(body), None


def main() -> int:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    md_files = sorted(p for p in DOCS_DIR.glob("*.md") if p.name != "manifest.json")
    results: list[dict] = []

    print(f"Comparing {len(md_files)} local files against about.zearn.org...\n")

    for i, path in enumerate(md_files):
        if i > 0:
            time.sleep(REQUEST_DELAY_SEC)

        meta, local_body = parse_markdown_file(path.read_text(encoding="utf-8"))
        local_body = strip_leading_h1(local_body)
        url = meta.get("source_url", "")

        entry: dict = {
            "file": path.name,
            "source_url": url,
            "status": "ok",
        }

        if not url:
            entry["status"] = "no_source_url"
            results.append(entry)
            continue

        live_body, error = fetch_live_body(session, url)
        if error:
            entry["status"] = "fetch_failed"
            entry["error"] = error
            results.append(entry)
            continue

        if live_body is None:
            entry["status"] = "no_live_body"
            results.append(entry)
            continue

        local_norm = normalize(local_body)
        live_norm = normalize(live_body)
        ratio = SequenceMatcher(None, local_norm, live_norm).ratio()
        word_delta = len(live_norm.split()) - len(local_norm.split())
        issues = find_issues(local_body, live_body)
        identical = local_body == live_body

        entry.update(
            {
                "identical": identical,
                "similarity": round(ratio, 4),
                "word_delta": word_delta,
                "issues": [{"kind": k, "value": v} for k, v in issues],
            }
        )

        if not identical or issues or ratio < 0.995 or abs(word_delta) >= 5:
            entry["status"] = "mismatch"
            diff = first_diff_excerpt(local_norm, live_norm)
            if diff:
                entry["local_excerpt"] = diff[0]
                entry["live_excerpt"] = diff[1]

        results.append(entry)
        status_mark = "✓" if entry["status"] == "ok" else "!"
        print(f"[{i + 1}/{len(md_files)}] {status_mark} {path.name}")

    mismatches = [r for r in results if r["status"] == "mismatch"]
    failed = [r for r in results if r["status"] not in {"ok", "mismatch"}]
    issue_files = [r for r in mismatches if r.get("issues")]

    mismatches.sort(key=lambda r: (r.get("similarity", 0), -abs(r.get("word_delta", 0))))

    print()
    print(f"Identical to live re-extract: {sum(1 for r in results if r.get('identical'))}")
    print(f"Mismatches: {len(mismatches)}")
    print(f"Fetch/extraction failures: {len(failed)}")
    print(f"Files with flagged issues: {len(issue_files)}")
    print()

    for entry in mismatches:
        if entry.get("identical") and not entry.get("issues"):
            continue
        print(
            f"## {entry['file']} (sim={entry.get('similarity')}, words {entry.get('word_delta', 0):+d})"
        )
        for issue in entry.get("issues", []):
            print(f"   - {issue['kind']}: {issue['value']}")
        if entry.get("local_excerpt"):
            print(f"   local: {entry['local_excerpt']!r}")
            print(f"   live:  {entry['live_excerpt']!r}")
        print(f"   {entry.get('source_url', '')}\n")

    if failed:
        print("=" * 60)
        print("FAILURES")
        for entry in failed:
            print(f"  {entry['file']}: {entry['status']} — {entry.get('error', '')}")

    report_path = DOCS_DIR / "live_compare_report.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nFull report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

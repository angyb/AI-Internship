#!/usr/bin/env python3
"""Compare local zendesk/md files against live Help Center article bodies."""

from __future__ import annotations

import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

from extract import USER_AGENT, prepare_article_content, html_to_markdown

BASE_URL = "https://help.zearn.org/api/v2/help_center/en-us"
DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "documents" / "zendesk" / "md"

GLUED_WORD_RE = re.compile(
    r"(?<=[a-z])(?=[A-Z])|"  # camelCase boundary
    r"(?<=\w)(?=\.)[A-Z]|"  # period then capital with no space
    r"canreview|rolepromoted|orClasslink|throughClever|ofIndependent|andLesson|ThePace|TheProgress|TheTower|TheSprint"
)
ESCAPED_NUMBER_RE = re.compile(r"^\d+\\\.")
INVISIBLE_CHAR_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060]")


def fetch_all_articles(session: requests.Session) -> dict[int, dict]:
    by_id: dict[int, dict] = {}
    url = f"{BASE_URL}/articles.json?per_page=100"
    while url:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()
        for article in data.get("articles", []):
            by_id[article["id"]] = article
        url = data.get("next_page")
        if url:
            time.sleep(0.2)
    return by_id


def parse_local_file(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    return meta, parts[2].strip()


def extract_live_body(body_html: str) -> str:
    soup = BeautifulSoup(f"<article>{body_html}</article>", "lxml")
    article = soup.find("article")
    if article is None:
        return ""
    prepare_article_content(article)
    return html_to_markdown(str(article)).strip()


def normalize(text: str) -> str:
    text = INVISIBLE_CHAR_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_glued_spans(local: str, live: str) -> list[str]:
    """Return local substrings that look glued but appear correctly spaced on live."""
    issues: list[str] = []
    for match in re.finditer(r"[A-Za-z]{3,}[A-Z][a-z]+|[a-z]+[A-Z][a-z]+", local):
        span = match.group(0)
        if span in live:
            continue
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", span)
        spaced = re.sub(r"(?<=\w)\.(?=[A-Z])", ". ", spaced)
        if spaced in live or spaced.lower() in live.lower():
            issues.append(span)
    for pattern in (
        "canreview",
        "rolepromoted",
        "orClasslink",
        "throughClever",
        "ofIndependent",
        "andLesson",
        "ThePace",
        "TheProgress",
        "TheTower",
        "TheSprint",
    ):
        if pattern in local and pattern not in live:
            issues.append(pattern)
    return sorted(set(issues))


def first_diff_excerpt(local: str, live: str, width: int = 120) -> tuple[str, str] | None:
    sm = SequenceMatcher(None, local, live)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        local_excerpt = local[max(0, i1 - 20) : i2 + 20]
        live_excerpt = live[max(0, j1 - 20) : j2 + 20]
        return local_excerpt[:width], live_excerpt[:width]
    return None


def main() -> int:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print("Fetching live article index...")
    live_articles = fetch_all_articles(session)
    print(f"  {len(live_articles)} articles from API")

    md_files = sorted(p for p in DOCS_DIR.glob("*.md") if p.name != "manifest.json")
    results: list[dict] = []

    for path in md_files:
        meta, local_body = parse_local_file(path)
        article_id = meta.get("article_id")
        if not article_id:
            results.append({"file": path.name, "status": "no_article_id"})
            continue

        live_article = live_articles.get(int(article_id))
        if not live_article:
            results.append({"file": path.name, "status": "not_in_api", "article_id": article_id})
            continue

        live_body = extract_live_body(live_article.get("body") or "")
        local_norm = normalize(local_body)
        live_norm = normalize(live_body)

        ratio = SequenceMatcher(None, local_norm, live_norm).ratio()
        glued = find_glued_spans(local_body, live_body)
        escaped_numbers = ESCAPED_NUMBER_RE.findall(local_body)
        invisible = bool(INVISIBLE_CHAR_RE.search(local_body))
        word_delta = len(live_norm.split()) - len(local_norm.split())

        status = "ok"
        if ratio < 0.98 or glued or escaped_numbers or invisible or abs(word_delta) >= 3:
            status = "mismatch"

        entry = {
            "file": path.name,
            "status": status,
            "similarity": round(ratio, 4),
            "word_delta": word_delta,
            "glued_patterns": glued,
            "escaped_numbers": len(escaped_numbers),
            "invisible_chars": invisible,
            "source_url": meta.get("source_url"),
        }
        if status == "mismatch":
            diff = first_diff_excerpt(local_norm, live_norm)
            if diff:
                entry["local_excerpt"] = diff[0]
                entry["live_excerpt"] = diff[1]
        results.append(entry)

    mismatches = [r for r in results if r["status"] == "mismatch"]
    mismatches.sort(key=lambda r: (r["similarity"], -abs(r.get("word_delta", 0))))

    print()
    print(f"Compared {len(md_files)} local files")
    print(f"Mismatches: {len(mismatches)}")
    print()

    for entry in mismatches:
        print(f"## {entry['file']} (similarity={entry['similarity']}, word_delta={entry['word_delta']:+d})")
        if entry.get("glued_patterns"):
            print(f"   glued: {', '.join(entry['glued_patterns'])}")
        if entry.get("escaped_numbers"):
            print(f"   escaped FAQ numbers: {entry['escaped_numbers']}")
        if entry.get("invisible_chars"):
            print("   invisible unicode characters present")
        if entry.get("local_excerpt"):
            print(f"   local: {entry['local_excerpt']!r}")
            print(f"   live:  {entry['live_excerpt']!r}")
        print(f"   {entry.get('source_url', '')}")
        print()

    out_path = DOCS_DIR / "live_compare_report.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Full report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

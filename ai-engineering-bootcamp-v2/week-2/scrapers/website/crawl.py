#!/usr/bin/env python3
"""Pilot scraper for about.zearn.org — static HTML extraction to markdown."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from extract import USER_AGENT, is_excluded_path, parse_sitemap, process_page_html, url_to_path

SITEMAP_URL = "https://about.zearn.org/sitemap.xml"
BASE_URL = "https://about.zearn.org"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent.parent / "documents" / "website" / "md"


def select_urls(
    sitemap: dict[str, str | None],
    sample_size: int,
    seed: int,
    must_include_paths: list[str],
) -> list[tuple[str, str | None]]:
    path_to_url: dict[str, tuple[str, str | None]] = {}
    for url, lastmod in sitemap.items():
        path = url_to_path(url)
        if is_excluded_path(path):
            continue
        path_to_url[path] = (url, lastmod)

    selected: dict[str, tuple[str, str | None]] = {}
    for path in must_include_paths:
        normalized = path if path.startswith("/") else f"/{path}"
        if is_excluded_path(normalized):
            print(f"  skipping excluded path: {normalized}")
            continue
        if normalized in path_to_url:
            selected[normalized] = path_to_url[normalized]
        else:
            full = urljoin(BASE_URL, normalized)
            selected[normalized] = (full, sitemap.get(full))

    remaining = [(p, v) for p, v in path_to_url.items() if p not in selected]
    rng = random.Random(seed)
    rng.shuffle(remaining)
    for path, entry in remaining[: max(0, sample_size)]:
        selected[path] = entry

    return list(selected.values())


def fetch_url(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape about.zearn.org pages to markdown")
    parser.add_argument("--must-include", action="append", default=["/how-zearn-math-works"])
    parser.add_argument("--sample", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sitemap", default=SITEMAP_URL)
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print(f"Fetching sitemap: {args.sitemap}")
    sitemap_xml = fetch_url(session, args.sitemap)
    sitemap = parse_sitemap(sitemap_xml)
    print(f"  {len(sitemap)} URLs in sitemap")

    urls = select_urls(sitemap, args.sample, args.seed, args.must_include)
    print(f"Selected {len(urls)} URLs for pilot crawl")

    manifest_entries = []
    ok_count = 0
    fallback_needed = 0
    total_deduped = 0

    for i, (url, lastmod) in enumerate(urls):
        if i > 0:
            time.sleep(args.delay)
        print(f"[{i + 1}/{len(urls)}] {url}")
        try:
            html = fetch_url(session, url)
            content, entry, error = process_page_html(html, url, lastmod, "static")
            manifest_entries.append(entry)
            total_deduped += entry.get("deduped_blocks_removed", 0)

            if content and entry["status"] == "ok":
                out_path = output_dir / entry["filename"]
                out_path.write_text(content, encoding="utf-8")
                ok_count += 1
                tabs = entry.get("tab_sections_labeled", 0)
                print(f"  ok → {entry['filename']} ({entry['word_count']} words, {tabs} tabs, -{entry['deduped_blocks_removed']} dupes)")
            elif entry["status"] == "excluded":
                print(f"  excluded: {error}")
            else:
                fallback_needed += 1
                print(f"  {entry['status']}: {error}")
        except Exception as exc:
            fallback_needed += 1
            entry = {
                "url": url,
                "filename": None,
                "status": "error",
                "extraction_method": "static",
                "word_count": 0,
                "deduped_blocks_removed": 0,
                "tab_sections_labeled": 0,
                "error": str(exc),
            }
            manifest_entries.append(entry)
            print(f"  error: {exc}")

    manifest = {
        "crawled_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sitemap": args.sitemap,
        "sample_size": args.sample,
        "seed": args.seed,
        "pages": manifest_entries,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    avg_deduped = total_deduped // max(len(urls), 1)
    hzmw = next((p for p in manifest_entries if "/how-zearn-math-works" in p.get("url", "")), None)
    hzmw_tabs = hzmw.get("tab_sections_labeled", 0) if hzmw else 0

    print()
    print(f"Fetched: {ok_count}/{len(urls)} (static)")
    print(f"Deduped: avg {avg_deduped} blocks/page removed")
    print(f"Tab sections labeled: {hzmw_tabs} on how-zearn-math-works")
    print(f"Output: {output_dir}/")
    print(f"Manifest: {manifest_path}")
    print(f"Playwright fallback needed: {fallback_needed} pages")

    return 0 if fallback_needed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

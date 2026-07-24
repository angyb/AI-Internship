#!/usr/bin/env python3
"""Discover and download zearn.org PDFs linked from help.zearn.org articles."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ZENDESK_DIR = Path(__file__).resolve().parent
WEBSITE_DIR = ZENDESK_DIR.parent / "website"
sys.path.insert(0, str(WEBSITE_DIR))

from crawl_pdfs import (  # noqa: E402
    discover_pdf_links,
    download_pdf,
    local_path_for_pdf,
    sha256_bytes,
    site_basenames,
)
from extract import USER_AGENT  # noqa: E402

_spec = importlib.util.spec_from_file_location("zendesk_extract", ZENDESK_DIR / "extract.py")
_zendesk_extract = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_zendesk_extract)
is_excluded_article = _zendesk_extract.is_excluded_article

BASE_URL = "https://help.zearn.org/api/v2/help_center/en-us"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent.parent / "documents" / "zendesk" / "pdf"


def fetch_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def paginate(session: requests.Session, endpoint: str) -> list[dict]:
    items: list[dict] = []
    url = f"{BASE_URL}/{endpoint}"
    while url:
        data = fetch_json(session, url)
        key = endpoint.split(".")[0]
        items.extend(data.get(key, []))
        url = data.get("next_page")
        if url:
            time.sleep(0.2)
    return items


def scan_help_center_pdfs(session: requests.Session) -> tuple[list[dict], dict[str, set[str]]]:
    articles = paginate(session, "articles.json?per_page=100")
    eligible = [article for article in articles if not article.get("draft") and not is_excluded_article(article)]

    pdf_sources: dict[str, set[str]] = {}
    article_scan_results: list[dict] = []

    for article in eligible:
        body = article.get("body") or ""
        article_url = article["html_url"]
        try:
            pdfs = discover_pdf_links(body, article_url)
            for pdf_url in pdfs:
                pdf_sources.setdefault(pdf_url, set()).add(article_url)
            article_scan_results.append(
                {
                    "url": article_url,
                    "title": article.get("title"),
                    "status": "ok",
                    "pdf_links_found": len(pdfs),
                    "error": None,
                }
            )
        except Exception as exc:
            article_scan_results.append(
                {
                    "url": article_url,
                    "title": article.get("title"),
                    "status": "error",
                    "pdf_links_found": 0,
                    "error": str(exc),
                }
            )

    return article_scan_results, pdf_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync zearn.org PDFs linked from help.zearn.org")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--download-delay", type=float, default=0.2, help="Seconds between PDF downloads")
    parser.add_argument("--skip-download", action="store_true", help="Discover PDFs only")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Remove local PDFs no longer linked from help center, then download missing ones",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print(f"Scanning help center articles from {BASE_URL}")
    article_scan_results, pdf_sources = scan_help_center_pdfs(session)
    scanned_ok = sum(1 for row in article_scan_results if row["status"] == "ok")
    print(f"  {scanned_ok}/{len(article_scan_results)} articles scanned")

    site_by_base = site_basenames(pdf_sources)
    unique_pdfs = sorted(pdf_sources)
    print(f"Unique zearn.org PDFs discovered: {len(unique_pdfs)}")

    removed = 0
    if args.sync:
        for local_file in sorted(output_dir.glob("*.pdf")):
            if local_file.name.lower() not in site_by_base:
                local_file.unlink()
                removed += 1
                print(f"removed stale → {local_file.name}")
        print(f"Removed {removed} stale PDF(s)")

    pdf_entries: list[dict] = []
    downloaded = 0
    skipped = 0
    failed = 0

    if args.skip_download:
        for pdf_url in unique_pdfs:
            dest = local_path_for_pdf(pdf_url, output_dir)
            pdf_entries.append(
                {
                    "url": pdf_url,
                    "filename": dest.name,
                    "status": "discovered",
                    "found_on_articles": sorted(pdf_sources[pdf_url]),
                    "bytes": None,
                    "sha256": None,
                    "error": None,
                }
            )
    else:
        for i, pdf_url in enumerate(unique_pdfs):
            if i > 0:
                time.sleep(args.download_delay)
            dest = local_path_for_pdf(pdf_url, output_dir)
            entry = {
                "url": pdf_url,
                "filename": dest.name,
                "found_on_articles": sorted(pdf_sources[pdf_url]),
                "bytes": None,
                "sha256": None,
                "error": None,
            }

            if dest.exists() and dest.stat().st_size > 0:
                data = dest.read_bytes()
                entry["bytes"] = len(data)
                entry["sha256"] = sha256_bytes(data)
                entry["status"] = "skipped_existing"
                skipped += 1
                pdf_entries.append(entry)
                continue

            print(f"[{i + 1}/{len(unique_pdfs)}] download {pdf_url}")
            try:
                size, digest = download_pdf(session, pdf_url, dest)
                entry["bytes"] = size
                entry["sha256"] = digest
                entry["status"] = "ok"
                downloaded += 1
                print(f"  ok → {dest.name} ({size:,} bytes)")
            except Exception as exc:
                entry["status"] = "error"
                entry["error"] = str(exc)
                failed += 1
                if dest.exists():
                    dest.unlink()
                print(f"  error: {exc}")

            pdf_entries.append(entry)

    manifest = {
        "crawled_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": BASE_URL,
        "articles_scanned": len(article_scan_results),
        "unique_pdfs": len(unique_pdfs),
        "removed_stale": removed,
        "downloaded": downloaded,
        "skipped_existing": skipped,
        "failed": failed,
        "article_scans": article_scan_results,
        "pdfs": pdf_entries,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print(f"Articles scanned: {len(article_scan_results)}")
    print(f"Unique PDFs linked: {len(unique_pdfs)}")
    if args.sync:
        print(f"Removed stale: {removed}")
    if not args.skip_download:
        print(f"Downloaded: {downloaded}")
        print(f"Skipped existing: {skipped}")
        print(f"Failed: {failed}")
    print(f"Local PDF count: {len(list(output_dir.glob('*.pdf')))}")
    print(f"Output: {output_dir}/")
    print(f"Manifest: {manifest_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

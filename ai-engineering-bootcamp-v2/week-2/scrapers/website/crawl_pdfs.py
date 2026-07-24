#!/usr/bin/env python3
"""Crawl about.zearn.org sitemap pages and sync zearn.org PDFs to a local folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from extract import USER_AGENT, is_excluded_path, parse_sitemap, url_to_path

SITEMAP_URL = "https://about.zearn.org/sitemap.xml"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent.parent / "documents" / "website" / "pdf"

PDF_URL_PATTERN = re.compile(
    r'https?://[^\s"\'<>]+\.pdf(?:\?[^\s"\'<>]*)?',
    re.IGNORECASE,
)
LINK_ATTRS = ("href", "src", "data-src", "data-href", "data-url", "data-file")


def normalize_pdf_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return urlunparse(("https", parsed.netloc.lower(), parsed.path or "/", "", "", ""))


def pdf_basename(url_or_name: str) -> str:
    path = urlparse(url_or_name).path if "://" in url_or_name else url_or_name
    return unquote(Path(path).name)


def local_path_for_pdf(url: str, output_dir: Path) -> Path:
    return output_dir / pdf_basename(url)


def is_zearn_domain(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "zearn.org" or host.endswith(".zearn.org")


def is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def discover_pdf_links(html: str, page_url: str) -> set[str]:
    found: set[str] = set()
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["a", "link", "iframe", "embed", "source"]):
        for attr in LINK_ATTRS:
            value = tag.get(attr)
            if not value:
                continue
            full = urljoin(page_url, value)
            if is_pdf_url(full) and is_zearn_domain(full):
                found.add(normalize_pdf_url(full))

    for match in PDF_URL_PATTERN.findall(html):
        if is_zearn_domain(match) and is_pdf_url(match):
            found.add(normalize_pdf_url(match))

    return found


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_url(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def download_pdf(session: requests.Session, url: str, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = session.get(url, timeout=60, stream=True)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and "pdf" not in content_type and "octet-stream" not in content_type:
        raise ValueError(f"unexpected content type: {content_type}")

    hasher = hashlib.sha256()
    size = 0
    with dest.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            handle.write(chunk)
            hasher.update(chunk)
            size += len(chunk)

    if size == 0:
        raise ValueError("empty file")

    return size, hasher.hexdigest()


def scan_site_pdfs(session: requests.Session, sitemap_url: str, delay: float) -> tuple[list[str], dict[str, set[str]], list[dict]]:
    sitemap = parse_sitemap(fetch_url(session, sitemap_url))
    page_urls = sorted(url for url in sitemap if not is_excluded_path(url_to_path(url)))

    pdf_sources: dict[str, set[str]] = {}
    page_scan_results: list[dict] = []

    for i, page_url in enumerate(page_urls):
        if i > 0:
            time.sleep(delay)
        print(f"[{i + 1}/{len(page_urls)}] scan {page_url}")
        try:
            html = fetch_url(session, page_url)
            pdfs = discover_pdf_links(html, page_url)
            for pdf_url in pdfs:
                pdf_sources.setdefault(pdf_url, set()).add(page_url)
            page_scan_results.append(
                {"url": page_url, "status": "ok", "pdf_links_found": len(pdfs), "error": None}
            )
        except Exception as exc:
            page_scan_results.append(
                {"url": page_url, "status": "error", "pdf_links_found": 0, "error": str(exc)}
            )
            print(f"  error: {exc}")

    return page_urls, pdf_sources, page_scan_results


def site_basenames(pdf_sources: dict[str, set[str]]) -> dict[str, str]:
    """Map lowercase basename -> canonical site URL."""
    by_base: dict[str, str] = {}
    for url in pdf_sources:
        base = pdf_basename(url).lower()
        by_base[base] = url
    return by_base


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync zearn.org PDFs linked from sitemap pages")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sitemap", default=SITEMAP_URL)
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between page requests")
    parser.add_argument("--download-delay", type=float, default=0.2, help="Seconds between PDF downloads")
    parser.add_argument("--skip-download", action="store_true", help="Discover PDFs only")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Remove local PDFs no longer linked on the site, then download missing ones",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print(f"Fetching sitemap: {args.sitemap}")
    page_urls, pdf_sources, page_scan_results = scan_site_pdfs(session, args.sitemap, args.delay)
    print(f"  {len(page_urls)} pages scanned")

    site_by_base = site_basenames(pdf_sources)
    unique_pdfs = sorted(pdf_sources)
    print(f"Unique zearn.org PDFs discovered: {len(unique_pdfs)}")

    removed = 0
    if args.sync:
        local_files = sorted(output_dir.glob("*.pdf"))
        for local_file in local_files:
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
                    "found_on_pages": sorted(pdf_sources[pdf_url]),
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
                "found_on_pages": sorted(pdf_sources[pdf_url]),
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
        "sitemap": args.sitemap,
        "pages_scanned": len(page_urls),
        "unique_pdfs": len(unique_pdfs),
        "removed_stale": removed,
        "downloaded": downloaded,
        "skipped_existing": skipped,
        "failed": failed,
        "page_scans": page_scan_results,
        "pdfs": pdf_entries,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print(f"Pages scanned: {len(page_urls)}")
    print(f"Unique PDFs on site: {len(unique_pdfs)}")
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

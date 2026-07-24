#!/usr/bin/env python3
"""Playwright fallback scraper for pages that fail static extraction."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent.parent / "documents" / "website" / "md"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from extract import USER_AGENT, process_page_html


def needs_fallback(entry: dict) -> bool:
    return entry.get("status") in ("static_failed", "incomplete", "error")


def fetch_with_playwright(url: str, delay: float = 0.5) -> str:
    if sync_playwright is None:
        raise RuntimeError("playwright not installed. Run: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_selector(".main-wrapper, nav.breadcrumbs_component.is-bg-white", timeout=30000)

        main_handle = page.query_selector(".main-wrapper")
        if main_handle is None:
            breadcrumb_handle = page.query_selector("nav.breadcrumbs_component.is-bg-white")
            footer_handle = page.query_selector("footer")
            if breadcrumb_handle is None or footer_handle is None:
                browser.close()
                raise RuntimeError("content root not found")
            html = page.content()
            browser.close()
            return html

        for link in main_handle.query_selector_all('[class*="feature-bar_link"], .w-tab-link'):
            try:
                link.click(timeout=3000)
                time.sleep(delay)
            except Exception:
                pass

        html = page.content()
        browser.close()
        return html


def main() -> int:
    parser = argparse.ArgumentParser(description="Playwright fallback for failed static scrapes")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--url", help="Re-scrape a single URL instead of reading manifest failures")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()

    if args.url:
        targets = [{"url": args.url, "filename": None, "status": "static_failed"}]
        lastmod_map: dict[str, str | None] = {}
    else:
        manifest_path = args.manifest.resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        targets = [p for p in manifest.get("pages", []) if needs_fallback(p)]
        lastmod_map = {p["url"]: None for p in manifest.get("pages", [])}

    if not targets:
        print("No pages need Playwright fallback.")
        return 0

    print(f"Re-scraping {len(targets)} page(s) with Playwright...")
    fixed = 0

    for entry in targets:
        url = entry["url"]
        print(f"  {url}")
        try:
            html = fetch_with_playwright(url)
            content, new_entry, error = process_page_html(
                html, url, lastmod_map.get(url), "playwright"
            )
            if content and new_entry["status"] == "ok":
                out_path = output_dir / new_entry["filename"]
                out_path.write_text(content, encoding="utf-8")
                new_entry["status"] = "playwright_ok"
                fixed += 1
                print(f"    playwright_ok → {new_entry['filename']}")
            else:
                print(f"    still failed: {error}")
        except Exception as exc:
            print(f"    error: {exc}")

    if args.url:
        return 0 if fixed else 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    by_url = {p["url"]: p for p in manifest.get("pages", [])}
    for entry in targets:
        if entry["url"] in by_url and fixed:
            pass  # manifest updated below on re-read if needed

    print(f"\nFixed: {fixed}/{len(targets)} pages")
    print("Re-run crawl.py to refresh manifest, or update manifest.json manually.")
    return 0 if fixed == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())

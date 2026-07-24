#!/usr/bin/env python3
"""Pilot scraper for help.zearn.org — Zendesk Help Center articles to markdown."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from extract import USER_AGENT, assign_doc_ids, is_excluded_article, process_article_page

BASE_URL = "https://help.zearn.org/api/v2/help_center/en-us"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent.parent / "documents" / "zendesk" / "md"


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


def load_help_center_index(session: requests.Session) -> tuple[list[dict], dict[int, dict], dict[int, dict]]:
    articles = paginate(session, "articles.json?per_page=100")
    sections = paginate(session, "sections.json?per_page=100")
    categories = paginate(session, "categories.json?per_page=100")
    section_by_id = {section["id"]: section for section in sections}
    category_by_id = {category["id"]: category for category in categories}
    return articles, section_by_id, category_by_id


def section_context(
    article: dict,
    section_by_id: dict[int, dict],
    category_by_id: dict[int, dict],
) -> tuple[str | None, str | None]:
    section = section_by_id.get(article.get("section_id"))
    if not section:
        return None, None
    category = category_by_id.get(section.get("category_id"))
    return section.get("name"), category.get("name") if category else None


def select_articles(
    articles: list[dict],
    sample_size: int,
    seed: int,
    must_include_ids: list[int],
) -> list[dict]:
    by_id = {article["id"]: article for article in articles}
    selected: dict[int, dict] = {}

    for article_id in must_include_ids:
        if article_id in by_id:
            selected[article_id] = by_id[article_id]

    remaining = [
        article
        for article in articles
        if article["id"] not in selected and not article.get("draft") and not is_excluded_article(article)
    ]
    rng = random.Random(seed)
    rng.shuffle(remaining)
    for article in remaining[: max(0, sample_size)]:
        selected[article["id"]] = article

    return list(selected.values())


def fetch_article_html(url: str) -> str:
    if sync_playwright is None:
        raise RuntimeError("playwright not installed. Run: pip install playwright && playwright install chromium")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("article header h1", timeout=30000)
        html = page.content()
        browser.close()
        return html


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape help.zearn.org articles to markdown")
    parser.add_argument("--sample", type=int, default=10, help="Random articles to scrape (0 = all)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--must-include-id", action="append", type=int, default=[])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between article page fetches")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print(f"Fetching help center index from {BASE_URL}")
    articles, section_by_id, category_by_id = load_help_center_index(session)
    print(f"  {len(articles)} articles, {len(section_by_id)} sections, {len(category_by_id)} categories")

    if args.sample == 0:
        selected = [a for a in articles if not a.get("draft") and not is_excluded_article(a)]
        print(f"Selected all {len(selected)} published articles")
    else:
        selected = select_articles(articles, args.sample, args.seed, args.must_include_id)
        selected = [a for a in selected if not is_excluded_article(a)]
        print(f"Selected {len(selected)} articles for pilot crawl (seed {args.seed})")

    published = [a for a in articles if not a.get("draft") and not is_excluded_article(a)]
    doc_ids = assign_doc_ids(published)

    manifest_entries = []
    ok_count = 0

    for i, article in enumerate(selected):
        if i > 0:
            time.sleep(args.delay)
        url = article["html_url"]
        print(f"[{i + 1}/{len(selected)}] {article.get('title', url)}")
        try:
            html = fetch_article_html(url)
            section_name, category_name = section_context(article, section_by_id, category_by_id)
            content, entry, error = process_article_page(
                article, html, section_name, category_name, "playwright", doc_id=doc_ids[article["id"]]
            )
            manifest_entries.append(entry)

            if content and entry["status"] == "ok":
                out_path = output_dir / entry["filename"]
                out_path.write_text(content, encoding="utf-8")
                ok_count += 1
                print(f"  ok → {entry['filename']} ({entry['word_count']} words)")
            else:
                print(f"  {entry['status']}: {error}")
        except Exception as exc:
            entry = {
                "url": url,
                "filename": None,
                "status": "error",
                "extraction_method": "playwright",
                "word_count": 0,
                "error": str(exc),
            }
            manifest_entries.append(entry)
            print(f"  error: {exc}")

    manifest = {
        "crawled_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": BASE_URL,
        "sample_size": args.sample,
        "seed": args.seed,
        "articles_total": len(articles),
        "pages": manifest_entries,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print(f"Fetched: {ok_count}/{len(selected)}")
    print(f"Output: {output_dir}/")
    print(f"Manifest: {manifest_path}")

    return 0 if ok_count == len(selected) else 1


if __name__ == "__main__":
    sys.exit(main())

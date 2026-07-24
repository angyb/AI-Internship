# Zendesk scraper (help.zearn.org)

Fetches Help Center articles via the Zendesk API for discovery, then loads each article page with Playwright and extracts the `<article>` element (including its `<header><h1>`), converts to markdown with YAML frontmatter, and writes reviewable files to `../../documents/zendesk/md/`.

The public HTML pages are Cloudflare-protected, so article pages are fetched with Playwright. The Zendesk API is used only to list articles and metadata.

## Setup

```bash
source ../../rag-vector-databases/.venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Pilot crawl (10 random articles)

```bash
python crawl.py
```

Defaults:
- 10 random published articles (seed 42)
- Output: `week-2/documents/zendesk/md/`

## Full crawl

```bash
python crawl.py --sample 0
```

## Extraction rules

- Content from the page `<article>` tag, including `<header><h1>`
- Removes `div.my-6[data-element="article-navigation"]` and `<footer>` inside the article
- No bold/italic formatting
- Images stripped entirely
- Links removed; inline link text preserved
- Block-only link CTAs removed
- Standalone lines starting with "Click here", "Learn more", or "Download and print" are removed

## Output format

Each markdown file has YAML frontmatter:

- `doc_id`, `source_url`, `title`, `source_site`, `source_type`, `language`
- `article_id`, `section`, `category`, `updated_at`, `scraped_at`, `word_count`, `extraction_method`

`manifest.json` logs crawl results per article.

## PDF downloads

Discover and download zearn.org PDFs linked from help center articles (via the Zendesk API article bodies):

```bash
python crawl_pdfs.py --sync
```

Output: `week-2/documents/zendesk/pdf/` plus `manifest.json`.

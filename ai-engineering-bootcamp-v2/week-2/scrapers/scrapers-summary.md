# Week 2 Scrapers — Summary for Week 3

This folder contains scrapers that built the **Zearn knowledge base** used by the Week 2 RAG system. Week 3 does not need to re-scrape unless you add new sources; the agent should call retrieval against what is already ingested.

## What this folder does

Two independent scrapers pull public Zearn content into reviewable files under `../documents/`:

| Scraper | Source | Output | Count (current) |
|---------|--------|--------|-----------------|
| `website/` | [about.zearn.org](https://about.zearn.org) (Webflow marketing site) | `../documents/website/md/` + `../documents/website/pdf/` | ~115 markdown pages, ~75 PDFs |
| `zendesk/` | [help.zearn.org](https://help.zearn.org) (Help Center) | `../documents/zendesk/md/` + `../documents/zendesk/pdf/` | ~138 markdown articles, ~76 PDFs |

**Total corpus:** ~400 source files → chunked and embedded into Pinecone by `../rag-vector-databases/ingest.py`.

## Website scraper (`website/`)

**Purpose:** Marketing, research, curriculum, and product pages from the public sitemap.

**Key files:**
- `crawl.py` — pilot/full crawl via static HTML (`requests` + BeautifulSoup)
- `extract.py` — parses `main.main-wrapper`, converts to markdown with YAML frontmatter
- `crawl_playwright.py` — fallback for JS-heavy pages (tab panels, etc.)
- `crawl_pdfs.py` — discovers and downloads PDFs linked from sitemap pages (zearn.org + Google Drive)
- `compare_live.py` — optional live-vs-markdown QA helper

**Run (pilot):**
```bash
cd ai-engineering-bootcamp-v2/week-2/scrapers/website
pip install -r requirements.txt
python crawl.py
```

**Output format:** Each `.md` file has YAML frontmatter with `doc_id`, `source_url`, `title`, `source_site`, `section`, `scraped_at`, etc. The `doc_id` becomes the RAG `document_id` at ingest time.

**Notable pages in corpus:** `how-zearn-math-works`, `getting-started`, `mission`, state standards PDFs, efficacy research PDFs.

## Zendesk scraper (`zendesk/`)

**Purpose:** Teacher/support how-to articles from the Help Center.

**Key files:**
- `crawl.py` — lists articles via Zendesk API, fetches HTML with Playwright (Cloudflare-protected)
- `extract.py` — extracts `<article>` content, strips nav/footer/images
- `crawl_pdfs.py` — downloads PDFs linked from article bodies
- `compare_live.py` — optional live-vs-markdown QA helper

**Run (pilot):**
```bash
cd ai-engineering-bootcamp-v2/week-2/scrapers/zendesk
pip install -r requirements.txt
playwright install chromium
python crawl.py
```

**Full crawl:** `python crawl.py --sample 0`

**Notable articles in corpus:** `add-students-to-your-class`, `tower-alerts-report`, `boosts`, `add-your-class`, `getting-started` (via cross-links), login/roster/admin reports.

## How scraped data flows to RAG

```
scrapers/website + scrapers/zendesk
        ↓
../documents/{website,zendesk}/{md,pdf}/
        ↓
../rag-vector-databases/ingest.py  →  chunk + embed  →  Pinecone index `zearn-rag`
        ↓
../rag-vector-databases/main.py    →  POST /ask, POST /retrieve
```

Week 3 should **reuse Pinecone + retrieval**, not re-run scrapers, unless you expand the corpus.

## Document identity (`document_id`)

At ingest, each source file becomes a `document_id`:

- Markdown: `doc_id` from YAML frontmatter, or filename stem (e.g. `add-students-to-your-class`)
- PDF: filename stem (e.g. `Zearn_Account_Comparison`, `EvaluationofZearnSupplementalwithDedicatedImplementationSupport`)

Chunk IDs follow `{document_id}__chunk_{index}` (e.g. `tower-alerts-report__chunk_0`).

The golden eval set in `../rag-vector-databases/golden_set.json` references these IDs as expected retrieval targets.

## When Week 3 might touch scrapers

| Scenario | Action |
|----------|--------|
| Agent only searches existing docs | No scraper work needed |
| Add new Help Center articles | Re-run `zendesk/crawl.py`, then `POST /ingest` |
| Add new marketing pages | Re-run `website/crawl.py`, then `POST /ingest` |
| New public API as a second tool | Separate from scrapers — add as ADK HTTP tool |

## Dependencies

- **Website:** `requests`, BeautifulSoup (see `website/requirements.txt`)
- **Zendesk:** `requests`, Playwright (see `zendesk/requirements.txt`)
- Shared venv with RAG is fine: `source ../rag-vector-databases/.venv/bin/activate`

## Related files outside this folder

- `../documents/` — scraped corpus (git-tracked)
- `../rag-vector-databases/corpus_audit.json` — metadata audit of all ingested docs (types, word counts, sections)
- `../rag-vector-databases/golden_set.json` — 5 eval questions tied to specific `document_id` values

# Website scraper (about.zearn.org)

Fetches pages from the Webflow sitemap, extracts content from `main.main-wrapper`, converts to markdown with YAML frontmatter, and writes reviewable files to `../../documents/website/md/`.

## Setup

From this directory:

```bash
pip install -r requirements.txt
```

Or use the week-2 RAG venv:

```bash
source ../../rag-vector-databases/.venv/bin/activate
pip install -r requirements.txt
```

## Pilot crawl (11 pages)

```bash
python crawl.py
```

Defaults:
- Always includes `/how-zearn-math-works`
- 10 random pages from sitemap (seed 42), excluding `/webinar-recordings/` paths
- Output: `week-2/documents/website/md/`

Options:

```bash
python crawl.py --sample 10 --seed 42 --must-include /how-zearn-math-works
python crawl.py --output-dir ../../documents/website/md
```

## Playwright fallback (only if static extraction fails)

```bash
pip install playwright
playwright install chromium
python crawl_playwright.py --manifest ../../documents/website/md/manifest.json
```

## Review checklist

After running the pilot, open files in `documents/website/md/` and verify:

- [ ] Nav, cookie banner, footer absent
- [ ] All tab panels present on `how-zearn-math-works.md` (9 `## Tab:` sections)
- [ ] No obvious duplicate paragraphs from responsive breakpoints
- [ ] Links preserved as `[text](url)`
- [ ] Frontmatter complete including `extraction_method`
- [ ] Claude in Chrome spot-check (optional): compare live tabs vs markdown

### Claude in Chrome QA (manual, not automated)

1. Open the live page in Chrome with the Claude extension
2. Open the matching `.md` file from `documents/website/md/`
3. Ask: "Does this markdown capture all tab content from the lesson tabs and TEACHERS / FAMILIES / SYSTEMS?"
4. Flag gaps → adjust selectors in `extract.py` → re-run `crawl.py`

## Output format

Each markdown file has YAML frontmatter:

- `doc_id`, `source_url`, `title`, `source_site`, `source_type`, `language`
- `path`, `section`, `description`, `lastmod`, `scraped_at`, `word_count`, `extraction_method`

`manifest.json` logs crawl results per URL (status, dedupe stats, tab count).

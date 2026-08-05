# Chrome Extension + Z-Bot Plan

**Status:** Ready to build. Backend complete; extension not started.

**Last updated:** 2026-08-05

**Prerequisite:** RAG + Google Search fallback — **COMPLETE**. Backend shipped through commit [`161bc16`](https://github.com/angyb/AI-Internship/commit/161bc16).

**Related docs:** [`zearn-support-agent-summary.md`](zearn-support-agent-summary.md) · [`rag-summary.md`](rag-summary.md) · [`README.md`](README.md)

---

## Build todos

| ID | Task | Status |
|----|------|--------|
| `verify-api` | Confirm Render `POST /agent` returns `{ answer, steps }` and `GOOGLE_API_KEY` is set | done |
| `scaffold-extension` | Create `../chrome-extension/` with MV3 manifest, content script matches for `*.zearn.org`, service worker | pending |
| `overlay-ui` | Shadow DOM overlay: Ask Z-Bot pill, question input, markdown answer (Sources links), collapsible Think/Act/Observe steps | pending |
| `api-proxy` | Background worker: `POST /agent` via `chrome.runtime.sendMessage`; 120s timeout; configurable `AGENT_API_URL`; surface FastAPI `detail` on errors | pending |
| `fallback-banners` | Web-fallback banner when answer contains `FALLBACK_PREFIX` or `google_search_agent` in steps; refusal banner on corpus miss | pending |
| `cold-start-mvp` | Wake `GET /health` before first `/agent`; show "Waking up API…" copy (Render free tier) | pending |
| `cors-optional` | Add FastAPI CORS middleware for chrome-extension origins (optional if proxy-only) | pending |
| `dev-readme` | Document load-unpacked workflow + how to add a new tool under `zearn_faq_bot/tools/` | pending |
| `harden-later` | Phase 3: API key auth, rate limits, Chrome Web Store listing before public release | pending |

---

## Naming

| What | Name | Notes |
|------|------|-------|
| **Extension UI label** | **Ask Z-Bot** | Pill/button text in the overlay |
| **Streamlit / page title** | **Zearn Support Agent** | Not "Teacher" |
| **Tools package** | **`zearn_faq_bot/`** | Colocated in `rag-vector-databases/` |
| **ADK agent** | **`zearn_support_agent`** | Unchanged |
| **Primary tool** | **`search_zearn_doc`** | Hybrid RAG retrieval (in-process on API) |
| **Fallback tool** | **`google_search_agent`** | ADK Agent-as-Tool |
| **API endpoint** | **`POST /agent`** | Not `/ask` |

---

## Current state (backend — done)

| Layer | Status | Key files |
|-------|--------|-----------|
| Documents | Scraped | [`../documents/website/`](../documents/website/), [`../documents/zendesk/`](../documents/zendesk/) |
| Vector store | **Pinecone** + in-process BM25 | [`ingest.py`](ingest.py), [`bm25_index.py`](bm25_index.py) — **16,364** chunks; BM25 rebuilt from Pinecone on API startup |
| Ingest metadata | PDF + markdown titles | Native `title` + `source_url` on every chunk; PDF titles from filename heuristics + `PDF_TITLE_OVERRIDES` in [`ingest.py`](ingest.py), suffixed with `(PDF)` |
| Retrieval API | Deployed | [`main.py`](main.py) — `POST /retrieve`, `/ask`, `/eval`, **`/agent`** |
| **Z-Bot (ADK agent)** | Built | [`zearn_faq_bot/`](zearn_faq_bot/) + shim [`zearn_support_agent.py`](zearn_support_agent.py) |
| Agent UI reference | Built | [`zearn_streamlit_app.py`](zearn_streamlit_app.py) — **port UX from here** |
| Golden-set eval | **6 questions** | [`golden_set.json`](golden_set.json) + [`eval_golden.py`](eval_golden.py) |
| Render API | Live | `https://ai-internship-i3lw.onrender.com` (`week-2-rag-api` in [`render.yaml`](render.yaml)) |
| Render UI | Live | `https://zearn-faq-bot.onrender.com` (`zearn-agent-ui`; `AGENT_API_URL` → API above) |

### Not used by the extension or agent

- **`rag_vector_db/`** — legacy local Chroma from the bootcamp notebook only. Moved **outside** `rag-vector-databases/` (not part of this project). Production retrieval uses **Pinecone**, not Chroma. No extension work depends on it.

### Shipped in recent commits

| Commit | Change |
|--------|--------|
| `cea3b7d` | Consolidated agent into week-2; Google Search fallback |
| `f8a2ba5` | Extracted `zearn_faq_bot/` package; empty Streamlit search field |
| `3052d76` | Agent cites Sources as markdown links; Pinecone + frontmatter enrichment |
| `c20ca87` | Removed duplicate Streamlit source block — answer text is sole citation UI |
| **`161bc16`** | PDF titles from filenames + overrides; golden set → 6 questions; README / rag-summary / agent summary / this plan |

### Backend details the extension inherits

- **Sources in answer only:** The agent writes a `Sources:` section with markdown links (`[Title](url)`) in the final answer. Do **not** add a second source list from Observe-step JSON — removed from Streamlit in `c20ca87` ([`zearn_streamlit_app.py`](zearn_streamlit_app.py) lines 177–192).
- **PDF link labels** include `(PDF)`, e.g. `[Zearn Account Comparison (PDF)](https://drive.google.com/...)`.
- **Observe steps** still include a `sources` array in JSON (optional raw-step panel); user-facing citations live in `answer`.
- **`search_zearn_doc`** returns `title`, `source_url`, `document_id` per chunk from Pinecone ([`zearn_faq_bot/tools/search_zearn_doc.py`](zearn_faq_bot/tools/search_zearn_doc.py)).
- **Agent model:** `GEMINI_MODEL` env (default `gemini-flash-latest`); `MAX_LLM_CALLS=15`.
- **No CORS middleware** on FastAPI yet — service-worker proxy is the recommended path.
- **Re-ingest:** Only when you intentionally refresh Pinecone (chunk/title logic changes). Confirm before running against the shared production index.

### Latest golden-set eval (local, `/ask` pipeline, 2026-08-05)

Run: `RAG_API_URL= python eval_golden.py` from this folder.

| Metric | Score |
|--------|-------|
| retrieval_hit | 100.00% (6/6) |
| faithfulness | 0.8667 |
| answer_correctness | 0.7146 |

Weakest answer: **"How do I add students to my class?"** (faithfulness 0.50). Extension surfaces the same agent behavior; improving that is a separate prompt/retrieval task.

**Nothing extension-related exists yet** — net-new frontend under [`../chrome-extension/`](../chrome-extension/).

---

## Architecture

```mermaid
flowchart TB
  subgraph extension [Chrome extension overlay]
    UI["Ask Z-Bot UI"]
    BG[service worker]
  end

  subgraph render [Render FastAPI]
    Health["GET /health"]
    AgentEP["POST /agent"]
    ADK["zearn_support_agent"]
    Retrieve["retrieve_context"]
  end

  subgraph zearnFaqBot [zearn_faq_bot]
    SearchDoc[search_zearn_doc]
    GoogleSearch[google_search_agent]
    FutureTools["your_new_tool ..."]
  end

  PC[(Pinecone + BM25)]

  UI --> BG
  BG -->|"wake"| Health
  BG -->|"question"| AgentEP
  AgentEP --> ADK
  ADK --> SearchDoc
  ADK --> GoogleSearch
  ADK --> FutureTools
  SearchDoc --> Retrieve
  Retrieve --> PC
  ADK -->|"answer + steps"| BG
  BG --> UI
```

**Why `POST /agent` not `/ask`:** Full agent loop — multi-step retrieval, Google Search fallback, Think/Act/Observe logs. New tools under `zearn_faq_bot/tools/` work after API redeploy with no extension changes.

---

## API contract (`POST /agent`)

Defined in [`main.py`](main.py) (`AgentRequest`, `AgentResponse`, `AgentStep`).

**Request:**
```json
{ "question": "How many students can I add to my class?" }
```

**Response:**
```json
{
  "answer": "Teachers with a free Individual Account can add up to 35 students.\n\nSources:\n- [Add students to your class](https://help.zearn.org/...)\n- [Zearn Account Comparison (PDF)](https://drive.google.com/...)",
  "steps": [
    { "phase": "Think", "author": "zearn_support_agent", "text": "..." },
    { "phase": "Act", "author": "zearn_support_agent", "tool": "search_zearn_doc", "args": { "question": "..." } },
    { "phase": "Observe", "author": "zearn_support_agent", "tool": "search_zearn_doc", "result": "{ \"chunk_count\": 1, \"sources\": [{\"title\": \"...\", \"source_url\": \"...\"}] }" }
  ]
}
```

**Client timeouts:** 120s (`AGENT_TIMEOUT_MS`). First Render request after idle may take up to ~60s — call `GET /health` first with the same timeout budget.

**Errors:** On HTTP 500, FastAPI returns `{ "detail": "..." }` (e.g. missing `GOOGLE_API_KEY`, agent failure). Surface `detail` in the overlay — do not fail silently.

**Fallback / refusal detection** — mirror [`zearn_streamlit_app.py`](zearn_streamlit_app.py):

```python
# Web fallback
FALLBACK_PREFIX in answer or any(
    step.get("tool") in ("google_search_agent", "google_search")
    for step in steps
)

# Corpus refusal
not web_fallback and (
    not answer.strip()
    or answer.strip() == REFUSAL_MESSAGE
    or "couldn't find that in the zearn documentation corpus" in answer.lower()
)
```

Constants: [`zearn_faq_bot/constants.py`](zearn_faq_bot/constants.py).

---

## Streamlit UX to port (reference implementation)

[`zearn_streamlit_app.py`](zearn_streamlit_app.py) is the canonical UI spec:

| Streamlit behavior | Extension equivalent |
|--------------------|---------------------|
| Empty question placeholder (`"Ask a Zearn support question..."`) | Empty input on open — no prefilled question |
| Steps **above** final answer | Collapsible Think/Act/Observe panel above answer |
| `st.markdown(answer)` — Sources links in answer body | Render answer markdown to HTML; **no second source block** |
| `st.info("Not found in Zearn docs — sourced from the web")` | Yellow fallback banner |
| `st.warning("Not found in corpus")` | Refusal banner |
| Cold-start spinner copy | "Running agent… first request may take up to a minute while the API wakes up." |
| Raw step JSON expander | Optional "Raw step data" collapsible (dev-friendly) |

Default hosted API: `https://ai-internship-i3lw.onrender.com`.

---

## Repo structure

```
AI-Internship/
  ai-engineering-bootcamp-v2/week-2/
    documents/                  # corpus (untouched by extension)
    scrapers/
    rag-vector-databases/       # FastAPI + agent + Streamlit (you are here)
      zearn_faq_bot/
      zearn_support_agent.py
      zearn_streamlit_app.py
      main.py
      ingest.py                 # PDF_TITLE_OVERRIDES, humanize_pdf_document_id()
      golden_set.json
      chrome-extension-plan.md  # this file
      zearn-support-agent-summary.md
    chrome-extension/           # NEW — this build
      manifest.json
      background.js
      content.js
      overlay.css
      overlay.js
      config.js
      vendor/                   # e.g. marked.min.js — MV3 forbids remote code
      README.md

  rag_vector_db/                # OUT OF PROJECT — notebook Chroma only (optional, local)
```

No re-architect required. Extension is standalone JS; only needs `POST /agent` (+ optional `GET /health` wake-up).

---

## Phase 1 — Overlay MVP

### 1. Scaffold (`../chrome-extension/`)

**`manifest.json` (MV3):**
- `manifest_version: 3`
- `permissions`: none if all fetch goes through service worker
- `host_permissions`: `https://ai-internship-i3lw.onrender.com/*` (and `http://127.0.0.1:8000/*` for local dev)
- `background.service_worker`: `background.js`
- `content_scripts`: `*://*.zearn.org/*`, `*://help.zearn.org/*`; `run_at: document_idle`
- Primary entry: in-page **Ask Z-Bot** pill (toolbar action optional)

### 2. Background service worker (`background.js`)

- Optional: `GET /health` before first `/agent` on a session (wake Render)
- `chrome.runtime.onMessage` → `{ type: "ask", question }`
- `fetch(AGENT_API_URL + "/agent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) })`
- 120s `AbortController` timeout
- Return `{ answer, steps }` or `{ error }` with FastAPI `detail` when present
- No API keys in extension

### 3. Content script + overlay (`content.js`, `overlay.js`, `overlay.css`)

- **Collapsed:** floating pill bottom-right — **"Ask Z-Bot"**
- **Expanded:** question input, Ask button, step log, answer area, close/minimize
- **Shadow DOM** for style isolation
- **No chat history in v1**
- **Markdown:** bundle a library (e.g. `marked`) under `vendor/` — **MV3 forbids remote/CDN scripts**. Render `[Title](url)` links and `Sources:` lists; do not duplicate sources from Observe JSON

### 4. Config (`config.js`)

```javascript
export const DEFAULT_AGENT_API_URL = "https://ai-internship-i3lw.onrender.com";
export const AGENT_TIMEOUT_MS = 120_000;
export const HEALTH_TIMEOUT_MS = 60_000;
// Override via chrome.storage.sync for local uvicorn
```

### 5. CORS (optional)

Service-worker proxy avoids CORS. Only add `CORSMiddleware` to [`main.py`](main.py) if calling the API directly from the content script.

---

## Local dev workflow (extension testing)

```bash
# Terminal 1 — API
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000

# Terminal 2 — compare against Streamlit (optional)
AGENT_API_URL=http://127.0.0.1:8000 streamlit run zearn_streamlit_app.py

# Chrome — load unpacked ../chrome-extension/
# Set AGENT_API_URL to http://127.0.0.1:8000 in extension config/storage
```

Quick API smoke test:

```bash
curl -s -X POST http://127.0.0.1:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"question":"What causes a Tower Alert?"}' | jq '{answer: .answer[0:200], step_tools: [.steps[].tool]}'
```

---

## Phase 2 — Polish

- Settings panel: override `AGENT_API_URL` via `chrome.storage.sync`
- Keyboard shortcut (e.g. `Alt+Z`)
- Zearn-adjacent styling (help center colors/fonts)

---

## Phase 3 — Harden (before public release)

- API key auth or signed tokens on `POST /agent`
- Rate limiting per install or IP
- Chrome Web Store listing + privacy policy
- Error telemetry (optional)

---

## Tool development workflow

1. Add tool under `zearn_faq_bot/tools/my_tool.py`
2. Register in [`zearn_faq_bot/agent.py`](zearn_faq_bot/agent.py)
3. Redeploy Render API (`week-2-rag-api`)
4. Extension picks up new capability automatically — no extension code changes

---

## Suggested build order

1. ~~Prerequisite: RAG + Google Search fallback~~ **DONE**
2. ~~Verify `POST /agent` on Render~~ **DONE**
3. ~~Pinecone metadata: `title` / `source_url`; PDF filename titles~~ **DONE** (`161bc16`)
4. ~~Fix duplicate Sources UI in Streamlit~~ **DONE**
5. ~~Project docs (README, summaries, this plan)~~ **DONE**
6. Scaffold `chrome-extension/` + MV3 manifest
7. Background worker → health wake + `POST /agent` + error `detail`
8. Shadow DOM overlay — pill, input, bundled markdown, step log
9. Fallback/refusal banners (copy Streamlit logic exactly)
10. `README.md` — load unpacked, local vs Render API
11. Manual test matrix on `help.zearn.org` + `zearn.org`
12. Phase 2 polish, then Phase 3 hardening

---

## Manual test matrix (extension MVP)

| Question | Expected |
|----------|----------|
| "What causes a Tower Alert and what is its purpose?" | `search_zearn_doc` in steps; Sources links in answer; no fallback banner |
| "What's the weather in New York?" | `google_search_agent` in steps; fallback banner; answer starts with `FALLBACK_PREFIX` |
| "How many students can I add to my class?" | Answer with Sources; links open help.zearn.org or PDF URLs; **one** source list only (in answer) |

Compare side-by-side with Streamlit at `https://zearn-faq-bot.onrender.com`.

---

## Success criteria for MVP

- User on `zearn.org` or `help.zearn.org` opens **Ask Z-Bot** and gets an answer via `/agent`
- Render cold-start handled (`/health` wake + user-facing wait copy)
- Answer renders markdown Sources links — **no duplicate source block** from Observe JSON
- Think/Act/Observe steps visible above the answer (matching Streamlit layout)
- Web fallback and corpus refusal banners match Streamlit
- API errors show FastAPI `detail`, not a blank failure
- New tools under `zearn_faq_bot/tools/` work after API redeploy — no extension changes
- No API keys exposed in extension bundle

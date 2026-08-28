# RAG + Vector Databases — Week 2 Zearn Project

Hybrid RAG over scraped Zearn docs (Pinecone + BM25), golden-set eval, and the **Zearn Support Agent** (ADK + Google Search fallback).

**Summaries:** [`rag-summary.md`](rag-summary.md) (full project) · [`how-it-works.md`](how-it-works.md) (code-level walkthrough) · [`zearn-support-agent-summary.md`](zearn-support-agent-summary.md) (agent) · [`chrome-extension-plan.md`](chrome-extension-plan.md) (extension) · [`../chrome-extension/ask-zbot-cloud-handoff.md`](../chrome-extension/ask-zbot-cloud-handoff.md) (cloud handoff)

The original bootcamp material lives in [`rag_vector_databases_live_session.ipynb`](rag_vector_databases_live_session.ipynb).

## Zearn Support Agent

ADK agent (`zearn_support_agent`) with tools **`search_zearn_doc`** (hybrid RAG) and **`google_search_agent`** (web fallback). Returns Think → Act → Observe steps and markdown **Sources** links in the answer.

| Surface | Command / URL |
|---------|----------------|
| **API** | `POST /agent` — `{ "question": "..." }` → `{ "answer", "steps" }` |
| **CLI** | `python zearn_support_agent.py "Your question"` |
| **Streamlit (local)** | `streamlit run zearn_streamlit_app.py` |
| **Streamlit (Render UI)** | `https://zearn-faq-bot.onrender.com` |
| **API (Render)** | `https://ai-internship-i3lw.onrender.com` |

**Requires:** `GOOGLE_API_KEY` for `/agent` and Streamlit local mode. Retrieval still uses `OPENAI_API_KEY` + Pinecone inside `search_zearn_doc`. Optional: `AGENT_API_KEY` (when set, `POST /agent` requires `X-API-Key`).

```bash
curl -s -X POST http://127.0.0.1:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"question":"What causes a Tower Alert?"}'
```

Package: [`zearn_faq_bot/`](zearn_faq_bot/). See [`zearn-support-agent-summary.md`](zearn-support-agent-summary.md) for architecture, test matrix, and env vars.

---

Deploy the Week 2 RAG API (`main.py`) as a Render **Web Service** from this GitHub repo.

1. Push your code to GitHub (do **not** commit `.env`).
2. In [Render](https://render.com): **New → Web Service** → connect the repo.
3. Settings:
   - **Root Directory:** `ai-engineering-bootcamp-v2/week-2/rag-vector-databases`  
     (required — there is no `main.py` at the repo root)
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements-render.txt`  
     (slim deps — no PyTorch; see [Render memory](#render-memory-512mb) below)
   - **Start Command:** `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment** — sync from your local `.env` (see [Sync env to Render](#sync-env-to-render) below), or add keys manually. Minimum required secrets:
   - `OPENAI_API_KEY`
   - `PINECONE_API_KEY`
   - `PINECONE_INDEX_NAME`
   - `PINECONE_HOST` (hostname only, no `https://`)
   - `GOOGLE_API_KEY` (required for **`POST /agent`**)
5. Deploy, then open your service URL (for example `https://your-app.onrender.com/docs`).

`render.yaml` defines two services: **`week-2-rag-api`** (FastAPI) and **`zearn-agent-ui`** (Streamlit agent demo). Both use this folder as `rootDir`.

If you see `Could not import module "main"`, the **Root Directory** is wrong or empty.

### Render memory (512MB)

Free/Starter Render instances have a **512MB RAM limit**. Loading PyTorch + the local cross-encoder reranker at startup exceeds that and causes **Out of memory (used over 512Mi)** / exit 137.

**On Render (512MB free tier), keep rerank off** — use `requirements-render.txt` and set
`RERANK_ENABLED=false`. On a **paid plan with ≥1GB RAM**, switch the build command to
`requirements.txt` and enable rerank (see `sync_render_env.py --full-deps`).

| Variable | Free-tier Render | Paid Render (≥1GB) |
|---|---|---|
| Build command | `requirements-render.txt` | `requirements.txt` |
| `RERANK_ENABLED` | `false` | `true` |
| `RELEVANCE_FILTER_ENABLED` | `false` | `true` |
| `CONTEXT_ORDER_BY_RERANK_SCORE` | `false` | `true` |

Hybrid BM25 + dense retrieval works on all tiers. Cross-encoder reranking needs the full deps.

### Sync env to Render

`render.yaml` lists every non-secret variable with values matching `.env.example`. To push your **local** `.env` (including API keys) to the Render Dashboard:

**Option A — Dashboard bulk paste (no API key)**

1. Generate a paste file: `python sync_render_env.py --print-bulk > .env.render.bulk`
2. Render → your service → **Environment** → **Add from .env**
3. Paste the contents of `.env.render.bulk` → **Save and deploy**

**Option B — Render API (automated)**

Add to your local `.env` (never commit real values):

```env
RENDER_API_KEY=rnd_...
RENDER_SERVICE_ID=srv_...
```

Then sync and redeploy in one command:

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
python sync_render_env.py --deploy
```

Preview without sending: `python sync_render_env.py --dry-run`

**When to re-run sync:** after any change to local `.env` that should match Render (retrieval, rerank, models, chunk size, etc.).

**When to re-ingest:** after changing `CHUNK_SIZE`, `CHUNK_OVERLAP`, `EMBEDDING_MODEL`, ingest/title logic in `ingest.py`, **or** after deploying slim Pinecone metadata (so existing vectors drop stored `text` bodies). Full ingest clears the Pinecone index by default and takes several minutes. Confirm before running against a shared production index.

After deploy, ingest documents once (from your machine or a one-off shell):

```bash
curl -X POST "https://your-app.onrender.com/ingest"
```

Then test:

```bash
curl -s -X POST "https://your-app.onrender.com/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I add students to my class?"}'
```

## Hybrid search (BM25 + vectors)

Retrieval combines **Pinecone dense search** with an in-process **BM25 keyword index**, fused via reciprocal rank fusion (RRF). This helps exact-term queries (e.g. `director`, `09:00`, `POL-101`) while keeping semantic matches strong.

- **Default:** hybrid is on for `/ask`, `/retrieve`, and `/eval`
- **Render startup:** BM25 loads from Postgres (`bm25_chunks`). If that table is empty, a **one-time** Pinecone metadata backfill runs (`include_values=false`) and writes Postgres, then never full-fetches the index again.
- **Ingest sync:** every `POST /ingest` updates Pinecone (vectors + slim metadata) **and** Postgres/BM25 (chunk text)
- **Disable:** set `HYBRID_SEARCH=false` in the environment to fall back to dense-only
- **Compare in Swagger:** `POST /retrieve` accepts `"use_hybrid": false` for dense-only debugging

Pinecone metadata no longer stores chunk bodies (ids, title, source_url only). Query/fetch use `include_values=false`. After this change, **re-ingest once** (or run the empty-table backfill while old vectors still have `text`) so existing vectors drop stored bodies and BM25 is populated.

## Retrieval tuning (env)

Values below match **`render.yaml`** (production). Local `.env` may differ — check yours before debugging.

| Variable | Render default | Purpose |
|---|---|---|
| `RETRIEVAL_K` | `5` | Final chunks passed to the LLM |
| `RETRIEVAL_FETCH_K` | `10` | Candidate pool when reranking is off |
| `MAX_CHUNKS_PER_DOCUMENT` | `1` | Per-document cap in final context |
| `NEIGHBOR_CHUNKS_ENABLED` | `false` | Append adjacent chunks for each hit |
| `NEIGHBOR_CHUNK_RADIUS` | `1` | How many neighbors on each side (`chunk_index ± N`) |
| `NEIGHBOR_MERGE_ENABLED` | `false` | Merge each hit + neighbors into one block |
| `MAX_CONTEXT_CHUNKS_ENABLED` | `true` | Cap blocks sent to the LLM after expand/merge |
| `MAX_CONTEXT_CHUNKS` | `5` | Maximum context blocks when cap is enabled |

After diverse filtering, neighbor expansion loads `chunk_index ± radius` from the same `document_id` (BM25/Postgres first, Pinecone fetch fallback). When merge is on, each hit becomes a single concatenated block; `MAX_CONTEXT_CHUNKS` then trims to the top blocks in retrieval order.

## Cross-encoder reranking (local, free)

After hybrid/dense retrieval, a **local cross-encoder** re-scores the top candidates and keeps the best `k` for the LLM context. No Cohere or other paid rerank API — runs on CPU via [sentence-transformers](https://www.sbert.net/docs/pretrained_cross-encoder.html).

- **Default model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80MB, downloaded on first startup)
- **Flow:** fetch `RERANK_CANDIDATES` (default 30) → cross-encoder score → per-document cap → final `k=5`
- **Render:** cross-encoder is **disabled** on 512MB instances (see [Render memory](#render-memory-512mb)); hybrid BM25 + dense retrieval only
- **Disable:** `RERANK_ENABLED=false` or `"use_rerank": false` on `POST /retrieve`
- **Override model:** `RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`

## Grounded generation

`/ask` routes each question to a **type-specific prompt** (how-to, comparison, research, report, etc.) via regex heuristics — no extra LLM call.

| Toggle | Values | Default | Effect |
|--------|--------|---------|--------|
| `TWO_STEP_GENERATION` | `true` / `false` | `false` | When `true`: extract facts from chunks, then answer from facts only (~2× generation tokens). When `false`: single-step answer directly from retrieved chunks (closer to source wording). |
| `QUESTION_ROUTING_ENABLED` | `true` / `false` | `true` | When `false`, uses the generic `general` template for all questions. |
| `ANSWER_VERBOSITY` | `concise` / `complete` | `concise` | `concise`: answer only what was asked; omit tangential details. `complete`: include related limits, triggers, and alternative paths. |
| `CITATIONS_ENABLED` | `true` / `false` | `false` | When `true`, prompts require markdown-link citations `[Title](url)` in answers. |
| `PROMPT_PROFILE` | type name or unset | unset | Force a prompt type for testing (e.g. `how_to`). |

Shared prompt rules (via `generation_config.py`): prefer verbatim source phrasing; do not add navigation, prerequisites, or comparisons unless the question asks for them.

- **Response field:** `/ask` returns `question_type` — the route chosen for that question.

## Pre-generation relevance filter

After neighbor expansion/merge, context blocks are scored with the same local cross-encoder used for reranking. Blocks scoring more than `RELEVANCE_MIN_SCORE_GAP` below the best block are dropped before the prompt is built.

| Toggle | Values | Default | Effect |
|--------|--------|---------|--------|
| `RELEVANCE_FILTER_ENABLED` | `true` / `false` | `true` | Enable/disable the filter |
| `RELEVANCE_MIN_SCORE_GAP` | float | `1.0` | Max allowed score drop from the best block |
| `RELEVANCE_MIN_CHUNKS` | int | `1` | Always keep at least this many blocks |

Tune `RELEVANCE_MIN_SCORE_GAP` if too many good chunks are dropped (increase) or boilerplate PDFs still leak through (decrease).

## Ingest chunking

| Toggle | Render default | Effect |
|--------|---------|--------|
| `CHUNK_SIZE` | `500` | Character chunk size for `POST /ingest` (when query params omitted) |
| `CHUNK_OVERLAP` | `80` | Overlap between consecutive chunks |

Changing these requires re-ingesting the corpus. PDF titles are derived from filenames (with overrides in `ingest.py`) and stored as metadata `title` + `source_url` on each chunk.

## OpenAI models

| Toggle | Default | Effect |
|--------|---------|--------|
| `ANSWER_MODEL` | `gpt-4o` | Chat model for `/ask` step 2 — structured answer generation. Override per request via `"model"` in the JSON body. |
| `EXTRACTION_MODEL` | falls back to `ANSWER_MODEL` | Chat model for two-step step 1 — fact extraction from retrieved chunks. Only used when `TWO_STEP_GENERATION=true`. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embeds questions at retrieval time and documents at ingest. Changing this requires re-ingest. |
| `RAGAS_JUDGE_MODEL` | `gpt-4o-mini` | LLM used by golden-set eval to score faithfulness and answer_correctness. |
| `GENERATION_TEMPERATURE` | `0` | Temperature for answer generation and fact extraction. |

Restart uvicorn after changing model env vars.

## Document scope for general queries

By default, `/ask` and `/retrieve` search the **full ingested corpus**. Golden-set eval uses `expected_document_ids` from `golden_set.json` when set.

- **Exclude specific docs:** set `EXCLUDE_DOCUMENT_IDS=doc_a,doc_b` (comma-separated)
- **Search everything explicitly:** pass `"exclude_document_ids": []` in the request body, or leave `EXCLUDE_DOCUMENT_IDS` unset
- **Restrict to specific docs:** pass `"document_ids": ["accessibility"]` (include wins over exclude)

Debug side-by-side rankings locally:

```bash
python debug_retrieve.py "How do I add students to my class?"
python debug_retrieve.py --dense-only "How do I add students to my class?"
```

## Streamlit demo UIs

### RAG pipeline (`demo_page.py`)

Calls `/ingest`, `/ask`, and `/eval` on your live API (no RAG logic in Streamlit).

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements-dev.txt
export RAG_API_URL=https://ai-internship-i3lw.onrender.com   # or set in .env
streamlit run demo_page.py
```

Use the **Eval** tab for golden-set eval screenshots.

### Zearn Support Agent (`zearn_streamlit_app.py`)

Calls **`POST /agent`** (local in-process or remote via `AGENT_API_URL`).

```bash
pip install -r requirements-streamlit.txt
streamlit run zearn_streamlit_app.py                                    # local agent
AGENT_API_URL=https://ai-internship-i3lw.onrender.com streamlit run zearn_streamlit_app.py  # Render API
```

Hosted UI: `https://zearn-faq-bot.onrender.com`

## Week 5 — Agentic Memory (Path A)

This capstone stores 1 durable user preference per anonymous `install_id` (a `role` of `student`, `teacher`, `parent`, or `admin` plus one or more `grade_bands` from `Kindergarten` through `Grade 8`): writes happen only when the UI user clicks **Save preference**, which sends `confirmed_write: true` to `POST /memory` (no chat/tool dumps are stored); the data lives in the API’s Postgres `user_memory` table on Render (or a local fallback JSON file during offline dev); every `POST /agent` call loads the stored preference for that `install_id` and seeds it into the agent so Session B can recall it without restating; forgetting is done via `DELETE /memory` (the UI **Forget preference** button) which removes the saved preference.

## Golden-set evaluation

Like Part 7 of `rag_vector_databases_live_session.ipynb`, but against your Pinecone pipeline and the **Zearn corpus** (~16k chunks after full ingest).

**Prerequisite:** run `POST /ingest` when you intend to refresh the index (see [Ingest chunking](#ingest-chunking)).

**Files:**
- `golden_set.json` — **6** questions with human-written reference answers and expected `document_id`s
- `eval_golden.py` — CLI runner (same logic as `POST /eval`; evaluates **`/ask`**, not the ADK agent)

**Metrics tracked:**

| Metric | What it measures |
|--------|------------------|
| `retrieval_hit` | Did top-k chunks include the expected `document_id`? (binary) |
| `faithfulness` | Is the answer supported by retrieved context? (RAGAS) |
| `answer_correctness` | How close is the answer to the reference? (RAGAS — your **correctness** score) |

### Option A — Streamlit (browser, recommended on Render)

1. Deploy the latest API to Render (includes `POST /eval` + RAGAS).
2. Run Streamlit locally and point it at Render:

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements-dev.txt
export RAG_API_URL=https://ai-internship-i3lw.onrender.com
streamlit run demo_page.py
```

3. Open the **Eval** tab and click **Run golden-set eval**.

The full pipeline runs on Render; Streamlit only displays the results.

### Option B — Render Swagger

After deploy, open `https://your-app.onrender.com/docs` → **POST /eval** → Execute (empty body is fine).

### Option C — Local terminal

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements-dev.txt
RAG_API_URL= python eval_golden.py
```

Unset `RAG_API_URL` if your `.env` points at localhost and the API is not running. To eval a remote API:

```bash
python eval_golden.py --api-url https://ai-internship-i3lw.onrender.com
```

**Assignment screenshot:** Eval tab or terminal output showing per-question scores and averages for all three metrics.

## 📝 License

This notebook is part of The AI Internship curriculum.


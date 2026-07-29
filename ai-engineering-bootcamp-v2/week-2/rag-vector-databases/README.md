# RAG + Vector Databases - Live Session Notebook

This notebook contains a complete, self-contained guide to building Retrieval Augmented Generation (RAG) systems with LangChain and Vector Databases.

## 📚 Contents

- **Why RAG Exists** - Understanding LLM limitations and RAG solutions
- **RAG Architecture** - Complete flow from indexing to query
- **Embeddings Deep Dive** - How text becomes vectors
- **Vector Databases** - Storing and searching semantic data
- **Chunking Strategies** - Critical techniques for good retrieval
- **Live Build** - Step-by-step Document Q&A system
- **Evaluation** - How to test and improve your RAG system

## 🚀 Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment:**
   Create a `.env` file with your OpenAI API key:
   ```
   OPENAI_API_KEY=your_api_key_here
   ```

3. **Open the notebook:**
   ```bash
   jupyter notebook rag_vector_databases_live_session.ipynb
   ```

4. **Run cells in order** - Each cell builds on the previous one

## 📋 Prerequisites

- Python 3.8 or higher
- Jupyter Notebook
- OpenAI API key (for embeddings and LLM calls)

## 🎯 Learning Objectives

By the end of this notebook, you will:
- Understand the complete RAG architecture
- Master embeddings and vector similarity search
- Build a production-ready Document Q&A system
- Know how to evaluate and debug RAG systems
- Be ready to build RAG applications on your own data

## 📖 Usage

This notebook is designed to be:
- **Self-contained** - All code and explanations included
- **Hands-on** - Run code as you learn
- **Production-ready** - Patterns you can use in real projects

## 🔧 Customization

To use with your own documents:
1. Replace the sample document with your PDF/text files
2. Adjust chunk sizes based on your document structure
3. Experiment with different embedding models
4. Add metadata filtering for your use case

## 📚 Additional Resources

- [LangChain Documentation](https://python.langchain.com/)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [OpenAI Embeddings Guide](https://platform.openai.com/docs/guides/embeddings)

## ⚠️ Notes

- This notebook requires an OpenAI API key
- API calls will incur costs (embeddings and LLM calls)
- For production, consider using local embedding models or managed services

## Deploy to Render

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
5. Deploy, then open your service URL (for example `https://your-app.onrender.com/docs`).

If you see `Could not import module "main"`, the **Root Directory** is wrong or empty.

### Render memory (512MB)

Free/Starter Render instances have a **512MB RAM limit**. Loading PyTorch + the local cross-encoder reranker at startup exceeds that and causes **Out of memory (used over 512Mi)** / exit 137.

**On Render, keep these off** (already set in `render.yaml` and forced by `sync_render_env.py`):

| Variable | Render value |
|---|---|
| `RERANK_ENABLED` | `false` |
| `RELEVANCE_FILTER_ENABLED` | `false` |
| `CONTEXT_ORDER_BY_RERANK_SCORE` | `false` |

Hybrid BM25 + dense retrieval still works. Tune reranking locally with `requirements.txt`, then sync other vars to Render.

To use cross-encoder reranking in production, upgrade to a Render plan with **≥1GB RAM** and switch the build command back to `requirements.txt`.

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

**When to re-run sync:** after any change to local `.env` that should match Render (retrieval, rerank, models, chunk size, etc.). If you change `CHUNK_SIZE`, `CHUNK_OVERLAP`, or `EMBEDDING_MODEL`, also run `POST /ingest` on Render after deploy finishes.

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
- **Render startup:** BM25 rebuilds from existing Pinecone vectors (so pasted ingests work without local files)
- **Ingest sync:** every `POST /ingest` updates both Pinecone and BM25
- **Disable:** set `HYBRID_SEARCH=false` in the environment to fall back to dense-only
- **Compare in Swagger:** `POST /retrieve` accepts `"use_hybrid": false` for dense-only debugging

## Retrieval tuning (env)

| Variable | Default | Purpose |
|---|---|---|
| `RETRIEVAL_K` | `5` | Final chunks passed to the LLM |
| `RETRIEVAL_FETCH_K` | `10` | Candidate pool when reranking is off |
| `MAX_CHUNKS_PER_DOCUMENT` | `2` | Per-document cap in final context |
| `NEIGHBOR_CHUNKS_ENABLED` | `true` | Append adjacent chunks for each hit |
| `NEIGHBOR_CHUNK_RADIUS` | `1` | How many neighbors on each side (`chunk_index ± N`) |
| `NEIGHBOR_MERGE_ENABLED` | `true` | Merge each hit + neighbors into one block per `(document_id, hit)` |
| `MAX_CONTEXT_CHUNKS_ENABLED` | `true` | Cap blocks sent to the LLM after expand/merge |
| `MAX_CONTEXT_CHUNKS` | `5` | Maximum context blocks when cap is enabled |

After diverse filtering, neighbor expansion loads `chunk_index ± radius` from the same `document_id` (BM25 index first, Pinecone fetch fallback). When merge is on, each hit becomes a single concatenated block; `MAX_CONTEXT_CHUNKS` then trims to the top blocks in retrieval order.

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

| Toggle | Default | Effect |
|--------|---------|--------|
| `CHUNK_SIZE` | `800` | Character chunk size for `POST /ingest` (when query params omitted) |
| `CHUNK_OVERLAP` | `100` | Overlap between consecutive chunks |

Changing these requires re-ingesting the corpus for vectors to match.

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

By default, `/ask` and `/retrieve` search the **full ingested corpus except `employee_handbook`**. Golden-set eval uses `expected_document_ids` from `golden_set.json` when set; otherwise it follows the same default exclude.

- **Default exclude:** `EXCLUDE_DOCUMENT_IDS=employee_handbook` (comma-separated for multiple IDs)
- **Search everything:** pass `"exclude_document_ids": []` in the request body, or set `EXCLUDE_DOCUMENT_IDS=false`
- **Restrict to specific docs:** pass `"document_ids": ["accessibility"]` (include wins over exclude)

Debug side-by-side rankings locally:

```bash
python debug_retrieve.py "director approval fully remote"
python debug_retrieve.py --dense-only "director approval fully remote"
```

## Streamlit demo UI

Minimal UI that calls `/ingest` and `/ask` on your live API (no RAG logic in Streamlit).

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements-dev.txt
export RAG_API_URL=https://your-app.onrender.com   # or set in .env
streamlit run demo_page.py
```

**Assignment screenshot:** capture the **Ask** tab after a successful question — show the sidebar with your Render URL, the answer, chunk_ids/sources under Citations, and (optionally) the **Ingest** tab with a pasted document + success message.

Use the **Eval** tab (see Golden-set evaluation below) for eval screenshots in the browser.

## Golden-set evaluation

Like Part 7 of `rag_vector_databases_live_session.ipynb`, but against your Pinecone pipeline and the **Zearn corpus** (404 documents after `POST /ingest`).

**Prerequisite:** run `POST /ingest` locally or on Render so Pinecone contains the full document set.

**Files:**
- `golden_set.json` — questions with human-written reference answers and expected `document_id`s
- `eval_golden.py` — CLI runner (same logic as `POST /eval`)

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
python eval_golden.py
```

To eval a remote API from the CLI:

```bash
python eval_golden.py --api-url https://ai-internship-i3lw.onrender.com
```

**Assignment screenshot:** Eval tab or terminal output showing per-question scores and averages for all three metrics.

## 📝 License

This notebook is part of The AI Internship curriculum.


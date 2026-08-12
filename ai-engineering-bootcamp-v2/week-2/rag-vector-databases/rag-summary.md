# Week 2 RAG + Zearn Support Agent — Project Summary

**Capstone:** Hybrid RAG (Pinecone + BM25) over scraped Zearn public docs, plus an ADK **Zearn Support Agent** with Google Search fallback, eval, and Streamlit UIs.

For agent-specific details see [`zearn-support-agent-summary.md`](zearn-support-agent-summary.md).  
For Chrome extension plans see [`chrome-extension-plan.md`](chrome-extension-plan.md).

---

## One-sentence jobs

**Week 2 pipeline (`POST /ask`):**  
> Retrieve relevant doc chunks from Pinecone and generate a grounded answer with OpenAI.

**Zearn Support Agent (`POST /agent`):**  
> The agent decides when to call `search_zearn_doc`, observes chunks, may search again, falls back to Google Search when docs fail, and returns a cited answer with step logs.

---

## Architecture

### RAG pipeline (workflow)

```
User question → POST /ask → retrieve_context() → generate_grounded_answer() → answer + chunk_ids
```

Hybrid search (dense + BM25, RRF), optional local cross-encoder rerank (off on Render 512MB), type-specific prompts via `question_classifier.py`.

### Support agent

```
User question → POST /agent → zearn_support_agent (Gemini)
    → search_zearn_doc → retrieve_context()
    → google_search_agent (fallback)
    → { answer, steps }
```

---

## Data source

Built from Week 2 scrapers → `../documents/`:

- **~115** website markdown pages + PDFs
- **~138** Zendesk help articles + PDFs
- **~16,364** chunks in Pinecone after full ingest

PDF chunk metadata includes human-readable **titles** (filename heuristics + overrides, suffixed with `(PDF)`) and **source_url** from crawl manifests or frontmatter.

See `../scrapers/scrapers-summary.md` for scraper details.

---

## Key files

| File | Role |
|------|------|
| `main.py` | FastAPI: `/health`, `/ingest`, `/retrieve`, `/ask`, `/eval`, **`/agent`** |
| `ingest.py` | Load docs, chunk, embed, upsert Pinecone; PDF title rules; hybrid retrieval |
| `bm25_index.py` | In-process BM25; rebuilt from Pinecone on startup |
| `rerank.py` | Cross-encoder rerank + relevance filter (local; off on Render) |
| `question_classifier.py` / `question_prompts.py` | `/ask` routing and templates |
| `eval_golden.py` / `golden_set.json` | Golden-set eval (6 questions) |
| `demo_page.py` | Streamlit for `/ingest`, `/ask`, `/eval` |
| **`zearn_faq_bot/`** | ADK agent package |
| **`zearn_support_agent.py`** | Shim + CLI |
| **`zearn_streamlit_app.py`** | Agent Streamlit UI |
| `render.yaml` | Render: API + agent UI services |
| `sync_render_env.py` | Push `.env` to Render |

---

## API endpoints

| Endpoint | Use |
|----------|-----|
| `GET /health` | Smoke test / wake Render |
| `POST /ingest` | Full corpus or single pasted doc → Pinecone + BM25 |
| `POST /retrieve` | Raw chunks (debug / tool backend) |
| `POST /ask` | Fixed RAG workflow (eval baseline) |
| `POST /eval` | Golden-set RAGAS eval |
| **`POST /agent`** | Zearn Support Agent |

---

## Deployed URLs

| Service | URL |
|---------|-----|
| API | `https://ai-internship-i3lw.onrender.com` |
| Agent UI | `https://zearn-faq-bot.onrender.com` |

Local: `uvicorn main:app --host 127.0.0.1 --port 8000`

---

## Config highlights (Render — see `render.yaml`)

| Setting | Render value |
|---------|----------------|
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 500 / 80 |
| `RETRIEVAL_K` / `RETRIEVAL_FETCH_K` | 5 / 10 |
| `MAX_CHUNKS_PER_DOCUMENT` | 1 |
| `NEIGHBOR_CHUNKS_ENABLED` | false |
| `HYBRID_SEARCH` | true |
| `RERANK_ENABLED` / `RELEVANCE_FILTER_ENABLED` | false |

Changing chunk size, overlap, or embedding model requires **`POST /ingest`** (clears and rebuilds the index by default). Re-ingest is slow (~3–4 min locally) and affects production if run against the shared Pinecone index — confirm before running.

---

## Eval baseline (local, `/ask` pipeline, 6 questions)

| Metric | Score |
|--------|-------|
| Retrieval hit | 100% (6/6) |
| Faithfulness | ~0.87 |
| Answer correctness | ~0.71 |

Weaker: add-students procedural answer (paraphrase vs numbered Roster steps).

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
RAG_API_URL= python eval_golden.py
```

---

## Running locally

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements.txt

# Terminal 1 — API
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Ingest (only when you intend to refresh the index)
curl -X POST http://127.0.0.1:8000/ingest

# Terminal 2 — RAG demo UI
streamlit run demo_page.py

# Terminal 3 — Agent UI (needs GOOGLE_API_KEY)
streamlit run zearn_streamlit_app.py

# Agent CLI
python zearn_support_agent.py "What causes a Tower Alert?"
```

---

## What’s done vs next

| Done | Next |
|------|------|
| Hybrid RAG + eval + Render deploy | Optional: improve add-students answer quality |
| ADK agent + Google Search fallback | Optional: agent-specific golden-set eval |
| Source links in agent answers | Optional: host privacy policy publicly + Chrome Web Store submit |
| Streamlit agent UI on Render | |
| **Chrome extension v1.0.0** (Phases 1–5: MVP → polish → harden → package → publish prep) | |

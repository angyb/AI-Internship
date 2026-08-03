# Week 2 RAG — Summary for Week 3

**Capstone:** A Zearn teacher/support FAQ bot backed by hybrid retrieval (Pinecone + BM25) over scraped public docs, exposed as a FastAPI service with eval and Streamlit demo.

Week 3 turns this from a **fixed pipeline** into an **agent** that *chooses* when to search docs. The retrieval layer below stays; wrap it as an ADK tool.

---

## One-sentence job (Week 2)

> When a teacher asks a Zearn question, **retrieve relevant doc chunks from Pinecone** and **generate a grounded answer** with OpenAI.

## One-sentence upgrade (Week 3)

> When a teacher asks a Zearn question, **the agent decides** whether and how to call `search_docs` (Week 2 retrieval), observes the chunks, then synthesizes an answer — possibly across multiple tool calls.

---

## Architecture (Week 2 pipeline)

```
User question
    ↓
POST /ask
    ↓
retrieve_context()          ← always runs
    ├─ hybrid search (Pinecone dense + in-process BM25, RRF fusion)
    ├─ optional cross-encoder rerank (local, CPU — off on Render 512MB)
    ├─ diverse filter (max 1 chunk per document by default)
    ├─ optional neighbor-chunk expansion
    ├─ relevance filter + context ordering (cross-encoder — off on Render)
    ↓
generate_grounded_answer()    ← type-specific prompts (how_to, comparison, …)
    ↓
JSON answer + chunk_ids + sources
```

This is a **workflow**, not an agent: every `/ask` follows the same path.

---

## Data source

Built from Week 2 scrapers → `../documents/`:

- **~115** website markdown pages + PDFs (`about.zearn.org`)
- **~138** Zendesk help articles + PDFs (`help.zearn.org`)
- **~16,000+** chunks in Pinecone index `zearn-rag` after full ingest

See `../scrapers/scrapers-summary.md` for scraper details.

---

## Key files

| File | Role |
|------|------|
| `main.py` | FastAPI app: `/health`, `/ingest`, `/retrieve`, `/ask`, `/eval` |
| `ingest.py` | Load docs, chunk, embed (`text-embedding-3-small`), upsert Pinecone; hybrid retrieval helpers |
| `bm25_index.py` | In-process BM25 index; rebuilt from Pinecone on startup |
| `rerank.py` | Local cross-encoder reranking + relevance filter (disabled on Render) |
| `question_classifier.py` | Regex routing to question types (how_to, comparison, research, …) |
| `question_prompts.py` | Type-specific generation templates |
| `generation_config.py` | Shared prompt rules (verbosity, citations, conflict resolution) |
| `retrieval_config.py` | Env-backed chunk/retrieval settings |
| `model_config.py` | OpenAI model names from env |
| `eval_golden.py` | Golden-set eval (retrieval hit, RAGAS faithfulness + answer_correctness) |
| `eval_format.py` | Markdown report formatting |
| `golden_set.json` | 5 Zearn eval questions with reference answers and expected `document_id`s |
| `demo_page.py` | Streamlit UI for `/ingest`, `/ask`, `/eval` |
| `sync_render_env.py` | Push local `.env` to Render (forces rerank off on 512MB) |
| `render.yaml` | Render deploy config (slim `requirements-render.txt`) |

---

## API endpoints (reuse in Week 3)

| Endpoint | Use for Week 3 |
|----------|-----------------|
| `GET /health` | Smoke test |
| `POST /ingest` | Re-index corpus after doc changes |
| `POST /retrieve` | **Best tool target** — returns raw chunks without generation |
| `POST /ask` | Full RAG pipeline (retrieve + generate) as a single HTTP call |
| `POST /eval` | Run golden-set eval on the server |

### `POST /retrieve` (recommended ADK tool backend)

```bash
curl -s -X POST http://127.0.0.1:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "What causes a Tower Alert?"}'
```

Returns `{ "chunks": [{ "chunk_id", "document_id", "text", "source" }, ...] }`.

### `POST /ask`

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I add students to my class?"}'
```

Returns answer, `chunk_ids`, `sources`, latency, token usage.

---

## Three ways Week 3 can call retrieval

### Option A — HTTP tool (simplest if Render is live)

ADK tool calls `POST /retrieve` or `POST /ask` on local uvicorn or Render URL.

- Pros: no import path issues, same behavior as production
- Cons: network hop; agent and API must both be running

### Option B — Python import (best for local agent)

ADK tool wraps `retrieve_context()` from `main.py`:

```python
from main import retrieve_context

def search_docs(question: str) -> dict:
    chunks, context, chunk_ids, sources = retrieve_context(question)
    return {"chunks": [...], "context": context, "chunk_ids": chunk_ids}
```

- Pros: direct, fast, full control over logging
- Cons: needs Week 2 venv + env vars (`OPENAI_API_KEY`, Pinecone, etc.)

### Option C — Hybrid

Agent uses `search_docs` (retrieve only); a separate generation step or second tool calls OpenAI with the returned context. Closer to true Think → Act → Observe separation.

---

## Current config highlights (local `.env`)

Typical tuned values (see `.env.example` for full list):

| Setting | Value | Notes |
|---------|-------|-------|
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 500 / 80 | Re-ingest if changed |
| `RETRIEVAL_K` | 5 | Final chunks to LLM |
| `MAX_CHUNKS_PER_DOCUMENT` | 1 | Diversity cap |
| `HYBRID_SEARCH` | true | BM25 + dense |
| `RERANK_ENABLED` | false (local) | true locally if enough RAM |
| `ANSWER_VERBOSITY` | concise | Misses alternate paths (e.g. class code) |
| `TWO_STEP_GENERATION` | false | Single-step answer from chunks |

**Render (512MB):** `RERANK_ENABLED`, `RELEVANCE_FILTER_ENABLED`, `CONTEXT_ORDER_BY_RERANK_SCORE` forced off via `sync_render_env.py` and `render.yaml`. Build uses `requirements-render.txt` (no PyTorch).

**Deploy URL:** `https://ai-internship-i3lw.onrender.com` (set `RAG_API_URL` in `.env`)

---

## Eval baseline (local, latest run)

Golden set: 5 questions in `golden_set.json`.

| Metric | Score |
|--------|-------|
| Retrieval hit | 100% (5/5) |
| Faithfulness | ~0.98 |
| Answer correctness | ~0.66 |

**Weaker questions:** Tower Alert (0.52), free account (0.54), science of learning (0.59). Add-students misses class-code alternate path due to concise verbosity + prompt rules.

**Run eval:**
```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
python eval_golden.py                    # local pipeline
python eval_golden.py --api-url https://ai-internship-i3lw.onrender.com  # Render
```

---

## Running locally

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements.txt          # includes PyTorch for local rerank

# Terminal 1 — API
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — ingest (first time or after doc/config changes)
curl -X POST http://127.0.0.1:8000/ingest

# Terminal 3 — Streamlit demo
streamlit run demo_page.py
```

Startup rebuilds BM25 from Pinecone (~16k vectors); first request may load cross-encoder if rerank features are enabled.

---

## Week 3 assignment checklist (using this project)

Path A requirements mapped to existing work:

| Requirement | How Week 2 helps |
|-------------|------------------|
| Real tool | Wrap `retrieve_context` or `POST /retrieve` as `search_docs` |
| Multi-step task | Agent searches → observes chunks → answers (or re-searches) |
| Think → Act → Observe | Log ADK events + tool return values |
| Streamlit UI | Adapt `demo_page.py` or ADK `streamlit_app.py` to show agent steps |
| Keep `/ask` working | Leave `main.py` unchanged; add agent as sibling module |
| Bounded loop | Cap ADK iterations at 8–12 |

**Suggested agent instruction:**  
*"You are a Zearn support agent. Before answering factual questions, call `search_docs`. Use only retrieved content. If the first search is insufficient, refine your query and search again. Cite document titles when possible."*

**Agent vs workflow one-liner:**  
*"This is an agent because the model decides when to search, can search multiple times with refined queries, and synthesizes only after observing retrieval results — unlike `/ask`, which always retrieves exactly once."*

---

## What not to duplicate in Week 3

- Re-scraping Zearn docs (unless expanding corpus)
- Re-implementing chunking/embedding (use ingest + Pinecone)
- Replacing OpenAI retrieval embeddings with Gemini (keep OpenAI for RAG; use Gemini for ADK agent orchestration)
- Submitting unchanged ADK Demo 1 (must adapt to Zearn + your retrieval tool)

---

## Related Week 3 sample code

Clone and run first (separate folder):

```
ai-engineering-bootcamp/adk-multi-agent-systems/
  demo1_routing.py      ← start here (router + local tools pattern)
  streamlit_app.py      ← Streamlit UI pattern
```

Adapt Demo 1's tool/agent pattern; replace fake `search_knowledge_base` with your real `search_docs`.

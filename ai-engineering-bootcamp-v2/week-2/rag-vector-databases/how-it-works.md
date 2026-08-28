# How It Works — Week 2 RAG + Zearn Support Agent

A code-level walkthrough of how this project fits together, meant as a reference for
future sessions. For higher-level summaries see [`rag-summary.md`](rag-summary.md),
[`zearn-support-agent-summary.md`](zearn-support-agent-summary.md), and the operator
docs in [`README.md`](README.md). This file focuses on **how the code actually behaves**.

---

## Overview

Two related systems live in this folder, both built around scraped Zearn docs:

1. **Hybrid RAG pipeline** — a FastAPI service that ingests docs into Pinecone,
   retrieves relevant chunks (dense + BM25), and generates grounded answers with OpenAI.
2. **Zearn Support Agent** — a Google ADK (Gemini) agent that *decides* when to search
   the RAG corpus, can search multiple times, and falls back to Google Search when the
   docs don't answer.

Everything is env-var driven, so behavior differs between **local** (full features) and
**Render** (512MB RAM, heavy features off).

### The two "brains" side by side

| | `POST /ask` (RAG pipeline) | `POST /agent` (Support Agent) |
|---|---|---|
| Orchestration | Fixed workflow | Gemini agent chooses tools |
| Retrieval | Always exactly once | 1+ times, agent-driven |
| Fallback | None | Google Search sub-agent |
| Model | OpenAI (`gpt-4o`) | Gemini (`gemini-3.6-flash`) |
| Output | Structured answer + chunk_ids + sources | Answer + Think/Act/Observe step log |

---

## 1. FastAPI service (`main.py`)

The backbone. On startup (`lifespan`) it:
- Loads the **BM25 keyword index** from Postgres (`bm25_chunks`). If the table is empty,
  a one-time Pinecone metadata backfill (`include_values=false`) fills Postgres, then
  future boots never re-download the index.
- Optionally warms up the cross-encoder reranker (background thread).

Endpoints:
- `GET /health` — smoke test / wake Render.
- `POST /ingest` — full corpus from disk, or a single pasted `{document_id, text}` doc.
- `POST /retrieve` — raw retrieved chunks (debugging + eval).
- `POST /ask` — the fixed RAG workflow (the eval baseline).
- `POST /eval` — runs the golden-set RAGAS evaluation server-side.
- `POST /agent` — runs the ADK support agent.

---

## 2. Ingestion (`ingest.py`)

Largest module. Full-ingest flow:

1. **Load** every `.md`, `.pdf`, `.txt` under `../documents/` (recursive), skipping
   `manifest.json`.
   - Markdown: parses YAML frontmatter for `title`/`source_url`/`doc_id`; falls back to
     first `# H1`.
   - PDF: one `Document` per page (PyMuPDF `fitz`, fallback `pypdf`). Titles derived from
     filenames via regex heuristics (CamelCase splitting, glued-connector fixing,
     grade-range `6_8`→`6-8`) plus a hardcoded `PDF_TITLE_OVERRIDES` table, all suffixed
     with `(PDF)`. Source URLs come from a crawl `manifest.json`.
2. **Chunk** with LangChain `RecursiveCharacterTextSplitter` (default 500 chars / 80
   overlap on Render). Small PDF pages are kept whole.
3. **Embed** with OpenAI `text-embedding-3-small`, **upsert** to Pinecone in batches of
   100. Metadata is slim (`document_id`, `chunk_index`, `source`, `title`, `source_url`)
   — not the chunk body. Chunk IDs are deterministic: `{document_id}__chunk_{index}`
   (index is per-document) — this is what makes neighbor lookups possible later.
4. **Sync BM25** — the same chunks (including full text) are written to Postgres
   `bm25_chunks` and the in-process BM25 index.

`clear_index=false` (API default) leaves existing vectors in place. Pass
`clear_index=true` to wipe Pinecone + BM25 first (requires `X-Override-Code` when
`AGENT_OVERRIDE_CODE` is set). Pasted single docs replace only their own
`document_id`.

---

## 3. Retrieval — the heart of the system

A multi-stage funnel assembled in `retrieve_context()` (`main.py`), using building blocks
from `ingest.py`, `bm25_index.py`, and `rerank.py`.

1. **Hybrid candidate fetch** (`retrieve_chunks_hybrid`)
   - **Dense**: embed the question, query Pinecone top-k with `include_values=false`, then
     hydrate chunk text from BM25/Postgres (legacy Pinecone `text` metadata is fallback).
   - **Sparse**: `BM25Okapi` keyword search over the in-process index (`bm25_index.py`) —
     helps exact-term queries (`POL-101`, `09:00`, `director`) that embeddings blur.
   - **Fuse** with **Reciprocal Rank Fusion** (`reciprocal_rank_fusion`, RRF constant 60):
     each list contributes `1/(60 + rank)`, then sort.
2. **Diversity filter** (`apply_diverse_filter`) — caps chunks per `document_id`
   (`MAX_CHUNKS_PER_DOCUMENT`, =1 on Render) so one long PDF can't dominate.
3. **Cross-encoder rerank** (`rerank.py`, *local only*) —
   `cross-encoder/ms-marco-MiniLM-L-6-v2` re-scores `(question, chunk)` pairs. Fetches ~30
   candidates, rescores, trims. **Disabled on Render** (PyTorch blows the 512MB limit →
   exit 137).
4. **Neighbor expansion / merge** (`prepare_context_chunks`) — since chunk IDs encode
   position, pulls `chunk_index ± radius` from the same doc to restore context cut off by
   chunking (appended or merged). Off by default on Render.
5. **Relevance filter + ordering** (`filter_and_order_chunks_by_relevance`) — another
   cross-encoder pass drops blocks scoring more than `RELEVANCE_MIN_SCORE_GAP` below the
   best block. Local-only.

Result: `(chunks, formatted_context, chunk_ids, sources)`.

**Document scoping** (`resolve_retrieval_filters`): an explicit include list wins;
otherwise apply `EXCLUDE_DOCUMENT_IDS` (default `employee_handbook`, so internal HR docs
never leak into public answers).

---

## 4. Generation (`main.py` + prompt modules)

`/ask` after retrieval:

1. **Classify the question** (`question_classifier.py`) — pure regex, no LLM. ~17 types
   (`how_to`, `comparison`, `research`, `report`, `troubleshooting`, …), first-match-wins,
   most-specific-first. Force with `PROMPT_PROFILE`; disable with
   `QUESTION_ROUTING_ENABLED=false`.
2. **Pick a template** (`question_prompts.py`) — each type has tailored fact-extraction
   and grounding `string.Template`s. Shared rule blocks (fidelity, verbosity, citations,
   conflict-resolution) injected from `generation_config.py`.
3. **Generate** — two modes:
   - **Single-step** (default on Render): answer directly from chunks.
   - **Two-step** (`TWO_STEP_GENERATION=true`): extract grouped facts, then answer only
     from those facts (~2× tokens, more faithful).
4. **Structured output** — `client.chat.completions.parse` forces a Pydantic
   `Answer{answer, confidence, sources_needed}`. A `force_bad` demo path
   (`call_model_unsafe`) returns invalid JSON to show schema-validation guardrails, with
   one automatic retry.

Response returns tokens, latency, computed `cost_usd`, `sources`, `chunk_ids`, and the
chosen `question_type`.

---

## 5. Zearn Support Agent (`zearn_faq_bot/`)

Google ADK agent wired in `agent.py`:
- **`search_zearn_doc`** (`tools/`) — calls the same `retrieve_context()` in-process, so
  the agent and `/ask` share one retriever. Backfills missing titles/URLs from local doc
  frontmatter/manifests; truncates chunk text to 500 chars.
- **`google_search_agent`** (`sub_agents/`) — sub-agent owning ADK's `google_search`, used
  only as fallback.

**Instruction** (`constants.py`) enforces the policy: search docs first; refine and search
again if needed; fall back to Google only when docs fail (answer must then start with the
exact `FALLBACK_PREFIX`); if both fail, return the exact `REFUSAL_MESSAGE`; never answer
from memory; cite sources as markdown links.

**Runner** (`runner.py`) drives ADK's async event loop and classifies each event into
**Think** (model text), **Act** (function call), or **Observe** (tool result) steps — this
powers the step log in the UI. Capped at `MAX_LLM_CALLS=15`.

`zearn_support_agent.py` is a thin shim (CLI + importable functions); `/agent` in
`main.py` calls `run_zearn_agent`.

---

## 6. Evaluation (`eval_golden.py`, `golden_set.json`, `eval_format.py`)

- `golden_set.json` — **6** questions with human reference answers and
  `expected_document_ids`.
- `eval_golden.py` — runs each question through the real retriever + `/ask` (locally
  in-process, or against a remote API via `--api-url`/`RAG_API_URL`), then scores with
  **RAGAS**:
  - `retrieval_hit` — did retrieved doc IDs intersect the expected set? (binary)
  - `faithfulness` — is the answer supported by context?
  - `answer_correctness` — closeness to the reference.
- RAGAS judge = `gpt-4o-mini`, with per-row retry for NaN scores (Render timeouts).
- Report rendered via `eval_format.py` in a fixed 4-section format (enforced by the
  `eval-golden-report` / `eval-golden-full-report` cursor rules — never truncate).

Retrieval runs over the **open corpus** (respecting `EXCLUDE_DOCUMENT_IDS`), *not* filtered
to expected docs — so the hit metric measures the retriever honestly, not an oracle filter.

Latest local baseline (6 questions): retrieval hit 100%, faithfulness ~0.87,
answer_correctness ~0.71 (weakest: procedural add-students answer).

---

## 7. Config, deployment, and the Render memory constraint

Recurring theme: **local = full power, Render = slim.**

- `env_utils.py` centralizes bool/int/float env parsing; `retrieval_config.py`,
  `model_config.py`, `generation_config.py`, `rerank.py` read env vars through it.
- `render.yaml` defines two services (FastAPI API + Streamlit agent UI) and hardcodes the
  memory-safe settings.
- **512MB RAM constraint**: PyTorch + cross-encoder OOMs (exit 137). On Render **rerank,
  relevance filter, and neighbor expansion are OFF** — only hybrid BM25 + dense retrieval
  runs. `requirements-render.txt` omits PyTorch; `requirements.txt` includes CPU-only torch
  for local use.
- `sync_render_env.py` pushes local `.env` to Render (bulk paste or API), forcing the
  memory-critical toggles off regardless of local values.
- Streamlit UIs (`demo_page.py` for RAG, `zearn_streamlit_app.py` for the agent) are thin
  frontends — they only call the API; no RAG logic lives in Streamlit.

---

## End-to-end data flow

- **Ingest (one-time):** `documents/` → load → chunk → embed → Pinecone (vectors + slim
  metadata) + Postgres `bm25_chunks` + in-memory BM25.
- **`/ask`:** question → classify type → hybrid retrieve (dense + BM25 + RRF) → diversity
  cap → *(local: rerank → neighbor expand → relevance filter)* → type-specific prompt →
  OpenAI structured answer → `{answer, sources, chunk_ids, cost, latency, question_type}`.
- **`/agent`:** question → Gemini decides → `search_zearn_doc` (same retriever) → maybe
  refine & search again → maybe `google_search_agent` fallback → cited answer +
  Think/Act/Observe steps.
- **`/eval`:** golden set → retrieve + `/ask` per question → RAGAS scores → formatted report.

---

## Gotchas for future work

- **Shared retriever**: `/ask` and the agent's `search_zearn_doc` use the same
  `retrieve_context()`. The agent inherits whatever retrieval config is active (e.g. no
  rerank on Render).
- **BM25 is per-process RAM, durable in Postgres**: startup loads `bm25_chunks` instead of
  fetching the whole Pinecone index. Multiple Render workers each load their own RAM copy.
  Fine for a single worker.
- **Defaults differ between code and `render.yaml`**: e.g. `RERANK_ENABLED` defaults `True`
  in `rerank.py` but is forced `false` on Render; `MAX_CHUNKS_PER_DOCUMENT` defaults 2 in
  code, 1 on Render. Easy source of "works locally, differs in prod" confusion — check the
  effective env before debugging.
- **`POST /agent` hardening** ([`agent_security.py`](agent_security.py)): when
  `AGENT_API_KEY` is set, callers (extension Settings, remote Streamlit) must send
  `X-API-Key`. Rate limits use `X-Install-Id` from the extension when present. Auth is a
  no-op when the env key is empty.

---

## Key file map

| File | Role |
|------|------|
| `main.py` | FastAPI app + `retrieve_context()` + generation orchestration |
| `agent_security.py` | Optional `AGENT_API_KEY` auth + rate limit + telemetry for `/agent` |
| `ingest.py` | Load/chunk/embed/upsert; PDF title rules; hybrid retrieval primitives |
| `bm25_index.py` | In-process BM25; rebuilt from Pinecone on startup |
| `rerank.py` | Cross-encoder rerank + relevance filter (local; off on Render) |
| `question_classifier.py` | Regex question-type routing |
| `question_prompts.py` | Per-type fact-extraction + grounding templates |
| `generation_config.py` / `model_config.py` / `retrieval_config.py` | Env-backed settings |
| `env_utils.py` | Shared bool/int/float env parsing |
| `eval_golden.py` / `golden_set.json` / `eval_format.py` | Golden-set RAGAS eval + report |
| `zearn_faq_bot/` | ADK agent package (agent, runner, tools, sub-agents, constants) |
| `zearn_support_agent.py` | Agent shim + CLI |
| `demo_page.py` / `zearn_streamlit_app.py` | Streamlit UIs (RAG / agent) |
| `render.yaml` / `sync_render_env.py` | Render deploy + env sync |

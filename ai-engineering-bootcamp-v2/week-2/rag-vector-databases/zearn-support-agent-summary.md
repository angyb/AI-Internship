# Zearn Support Agent — Summary

An ADK agent that answers Zearn teacher and admin support questions by searching a hybrid RAG corpus, with Google Search fallback when docs do not answer. Exposed as `POST /agent` on the Week 2 FastAPI service and via a Streamlit demo UI.

---

## One-sentence job

> When someone asks a Zearn support question, **the agent decides** whether to call `search_zearn_doc`, may refine and search again, falls back to **Google Search** when the corpus does not answer, and returns a cited final answer with Think → Act → Observe step logs.

---

## Architecture

```
User question
    ↓
POST /agent  (or Streamlit / future Chrome extension)
    ↓
zearn_support_agent  (Gemini via ADK)
    ├─ search_zearn_doc  → retrieve_context() in-process (Pinecone + BM25)
    └─ google_search_agent  (sub-agent, AgentTool) when docs fail
    ↓
{ answer, steps }
```

Unlike `POST /ask`, the agent **chooses** when and how to retrieve, can call tools multiple times, and synthesizes only after observing tool results.

---

## Package layout

```
rag-vector-databases/
  zearn_faq_bot/
    agent.py                 # zearn_support_agent wiring
    constants.py             # instructions, FALLBACK_PREFIX, REFUSAL_MESSAGE
    runner.py                # ADK runner + Think/Act/Observe step logging
    tools/search_zearn_doc.py
    sub_agents/google_search_agent.py
  zearn_support_agent.py     # thin shim + CLI
  zearn_streamlit_app.py     # Streamlit UI (local or remote API)
  main.py                    # POST /agent
```

Add new tools under `zearn_faq_bot/tools/` — see [`ADDING_A_TOOL.md`](ADDING_A_TOOL.md). Register on the agent in `agent.py`, redeploy the API — no Streamlit or extension changes required per tool.

---

## Tools

| Tool | Role |
|------|------|
| `search_zearn_doc` | Hybrid retrieval over ~16k Pinecone chunks; returns chunk text, `title`, `source_url`, `document_id` |
| `google_search_agent` | Web fallback via ADK `google_search`; answer must start with `FALLBACK_PREFIX` |

**Corpus refusal:** If both tools fail, the agent returns exactly `REFUSAL_MESSAGE` from `constants.py`.

**Web fallback label:** `"This wasn't found in Zearn documentation; sourced from the web."`

---

## Citations

- The agent instruction requires **Sources** as markdown links in the final answer (`[Title](url)` from chunk metadata).
- PDF titles are derived from filenames (CamelCase / underscore splitting + overrides); each ends with `(PDF)`.
- Markdown articles use frontmatter `title` and `source_url`.
- Pinecone vectors store native `title` and `source_url` after ingest.
- Streamlit renders the answer markdown only — **no duplicate source block** from Observe-step JSON.

---

## API — `POST /agent`

**Request:**
```json
{ "question": "What causes a Tower Alert?" }
```

**Response:**
```json
{
  "answer": "...",
  "steps": [
    { "phase": "Think", "author": "zearn_support_agent", "text": "..." },
    { "phase": "Act", "tool": "search_zearn_doc", "args": { "question": "..." } },
    { "phase": "Observe", "tool": "search_zearn_doc", "result": "..." }
  ]
}
```

**Requires:** `GOOGLE_API_KEY` (Gemini for ADK). Retrieval still uses OpenAI embeddings + Pinecone via `search_zearn_doc`.

**Timeout:** Allow ~120s on first request (Render cold start).

```bash
curl -s -X POST http://127.0.0.1:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"question":"What causes a Tower Alert?"}'
```

---

## Streamlit UI

**Local (in-process agent):**
```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements-streamlit.txt
# GOOGLE_API_KEY in .env; optional uvicorn for /health sidebar check
streamlit run zearn_streamlit_app.py
```

**Remote (Render API):**
```bash
AGENT_API_URL=https://ai-internship-i3lw.onrender.com streamlit run zearn_streamlit_app.py
```

UI shows Think → Act → Observe steps, final answer with Sources links, and banners for web fallback or corpus refusal.

---

## Deployed services (Render)

| Service | URL | Role |
|---------|-----|------|
| `week-2-rag-api` | `https://ai-internship-i3lw.onrender.com` | FastAPI: `/ask`, `/retrieve`, `/eval`, **`/agent`** |
| `zearn-agent-ui` | `https://zearn-faq-bot.onrender.com` | Streamlit → `AGENT_API_URL` above |

Both use `rootDir: ai-engineering-bootcamp-v2/week-2/rag-vector-databases` (`render.yaml`).

---

## Environment

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` | ADK agent + Google Search sub-agent |
| `GEMINI_MODEL` | Agent model (default `gemini-3.6-flash`) |
| `AGENT_DAILY_ASK_LIMIT` | Global asks per UTC day (default `100`; `0` disables) |
| `AGENT_OVERRIDE_CODE` | Unlock code; send as `X-Override-Code` to skip the daily cap |
| `OPENAI_API_KEY` | Embeddings + `/ask` generation |
| `PINECONE_*` | Vector index |
| `AGENT_API_URL` | Streamlit remote mode (UI service) |

RAG retrieval env vars are the same as the Week 2 pipeline (see `README.md` and `render.yaml`).

---

## Manual test matrix

| Question | Expected |
|----------|----------|
| Tower Alert | `search_zearn_doc` only; Sources in answer; no fallback prefix |
| Weather in New York | `google_search_agent` in steps; answer starts with `FALLBACK_PREFIX` |
| How many students can I add? | RAG answer with Sources links to help.zearn.org |

Compare with hosted UI: `https://zearn-faq-bot.onrender.com`

---

## Golden-set eval (RAG pipeline, not agent)

Eval runs the **`/ask` pipeline** (not the ADK agent) unless you add agent-specific eval later.

```bash
RAG_API_URL= python eval_golden.py   # local; unset RAG_API_URL if .env points at dead localhost
```

Latest local run (6 questions): retrieval hit 100%, faithfulness ~0.87, answer_correctness ~0.71. Weakest: procedural add-students answer.

---

## Next build: Chrome extension

**Phases 1–5 complete** (v1.0.0) under [`../chrome-extension/`](../chrome-extension/). See [`chrome-extension-plan.md`](chrome-extension-plan.md). Remaining: human Web Store submit + public privacy URL if publishing.

---

## Agent vs `/ask`

| | `POST /ask` | `POST /agent` |
|---|-------------|---------------|
| Orchestration | Fixed workflow | ADK agent chooses tools |
| Retrieval | Always once | `search_zearn_doc`, possibly multiple queries |
| Fallback | None | Google Search sub-agent |
| Model | OpenAI (`ANSWER_MODEL`) | Gemini (`GEMINI_MODEL`) |
| Output | Answer + chunk_ids + sources | Answer + Think/Act/Observe steps |
| Best for | Eval baseline, simple API | Interactive support, extension, multi-step UX |

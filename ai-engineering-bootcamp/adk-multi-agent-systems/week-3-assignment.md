# Week 3 Assignment — Turn Your Capstone into an Agent

Personal plan for evolving the **Week 2 Zearn RAG capstone** into a **Google ADK agent** with a real tool, Think → Act → Observe proof, and a Streamlit UI.

---

## What this assignment is

Session 3 turns your assistant from a **one-shot pipeline** into an **agent**: it plans, calls at least one real tool, observes the result, and decides again.

| Week 2 (`/ask`) | Week 3 (agent) |
|-----------------|----------------|
| Always retrieve → always answer | Model **chooses** when to search |
| Fixed steps in Python | Think → Act → Observe loop |
| OpenAI orchestrates generation | **Gemini (ADK)** orchestrates; Week 2 retrieval is a **tool** |

You are **not** replacing search — you are wrapping it so the model decides **when and how** to use it.

---

## Path A — basic submission (enough to pass)

Do these in order. Stop when the checklist at the bottom is complete.

### 1. Pick the job (one sentence)

Write this before coding:

> **When** a teacher asks a Zearn support question, **the agent should** search the Zearn knowledge base and produce a grounded answer **using** a `search_docs` tool (Week 2 retrieval).

If you cannot write one sentence like that, the job is still too vague.

### 2. Run the ADK sample first

```bash
cd ai-engineering-bootcamp/adk-multi-agent-systems
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env          # add GOOGLE_API_KEY from https://aistudio.google.com/apikey
python demo1_routing.py       # router → specialists with local tools
streamlit run streamlit_app.py  # optional: see UI pattern
```

**What each demo proves:**

| Demo | File | Shows |
|------|------|-------|
| Demo 1 | `demo1_routing.py` | Router + specialist agents + **local Python tools** |
| Demo 2 | `demo2_mcp.py` | MCP + Supabase (stretch) |
| Demo 3 | `demo3_full_system.py` | Routing + MCP + A2A (stretch) |

Start with **Demo 1 only**. Do not submit an unchanged demo as homework.

### 3. Understand what Week 2 already gives you

Read these handoff docs (same repo, Week 2 folder):

- `ai-engineering-bootcamp-v2/week-2/rag-vector-databases/rag-summary.md` — API, retrieval, eval, how to wire tools
- `ai-engineering-bootcamp-v2/week-2/scrapers/scrapers-summary.md` — where Zearn docs came from

**Week 2 capstone recap:**

- **Corpus:** ~400 Zearn source files (website + Zendesk help center) → ~16k Pinecone chunks
- **FastAPI:** `/health`, `/ingest`, `/retrieve`, `/ask`, `/eval`
- **Retrieval:** hybrid BM25 + dense (Pinecone), optional local rerank
- **Deploy:** Render at `https://ai-internship-i3lw.onrender.com` (rerank disabled on 512MB)
- **Eval:** 5-question golden set; last local run ~100% retrieval hit, ~0.66 answer correctness

Week 2 `/ask` **always** retrieves. Week 3 adds a layer where the **agent** calls retrieval as a tool.

### 4. Build a minimal Zearn support agent

Create a new file in this folder (suggested name: `zearn_support_agent.py`). Copy patterns from `demo1_routing.py`:

**Agent (one root agent is enough for Path A):**

- **Model:** `gemini-2.5-flash` (or current Gemini model from sample)
- **Instruction:** Search docs before answering factual questions; use only retrieved content; refine query and search again if needed
- **Tools:** `search_docs` (real — see below)
- **Loop cap:** 8–12 max iterations — fail closed when cap is hit

**Real tool — pick one approach:**

| Approach | How | When to use |
|----------|-----|-------------|
| **A. HTTP** | Tool calls `POST /retrieve` on local uvicorn or Render | Simplest; no import path issues |
| **B. Python import** | Tool calls `retrieve_context()` from Week 2 `main.py` | Local dev; full control |
| **C. Hybrid** | Tool returns chunks only; agent synthesizes answer | Clearest Think/Act/Observe separation |

**Recommended first tool (HTTP):**

```bash
# Week 2 API must be running
curl -X POST http://127.0.0.1:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "What causes a Tower Alert?"}'
```

Wrap that in an ADK function tool named `search_docs(question: str) -> dict`.

**Env vars needed:**

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` | ADK agent (Gemini) — add to this folder's `.env` |
| `OPENAI_API_KEY` | Week 2 retrieval/embeddings — already in Week 2 `.env` |
| `PINECONE_*` | Week 2 Pinecone — already in Week 2 `.env` |
| `RAG_API_URL` | Optional — Render or `http://127.0.0.1:8000` for HTTP tool |

### 5. Prove Think → Act → Observe

Run one task that **requires** the tool (not answerable from memory alone):

**Good test question:** *"What causes a Tower Alert and what is its purpose?"*

You should see:

1. **Think** — model decides to call `search_docs`
2. **Act** — tool runs; Pinecone/BM25 returns chunks
3. **Observe** — tool result returned to model
4. **Think again** — model writes final answer using chunks

Save ADK run logs or record a **30–60s Loom** walking through one run.

Map ADK events to Think/Act/Observe if the framework uses different labels.

### 6. Streamlit UI (required)

Path A requires a Streamlit UI that demos the agent. Options:

- Adapt `streamlit_app.py` in this folder for your Zearn agent
- Or adapt Week 2 `demo_page.py` to show agent step logs instead of raw `/ask`

**UI must:**

1. Let you enter a user task / question
2. Show Think → Act → Observe (or step logs)
3. Show the final answer clearly
4. Not hardcode API keys (use `.env`)

**Run:**

```bash
# Terminal 1 — Week 2 API (if using HTTP tool)
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — Zearn agent Streamlit
cd ai-engineering-bootcamp/adk-multi-agent-systems
source .venv/bin/activate
streamlit run zearn_streamlit_app.py   # or your UI file
```

### 7. Write your one-liner

Submit with your proof:

> **Agent vs workflow:** This is an agent because the model decides when to search the Zearn docs, can search multiple times with refined queries, and only answers after observing retrieval results — unlike Week 2 `/ask`, which always retrieves exactly once in a fixed pipeline.

Adjust honestly if your implementation is still always search-then-answer (that would be a workflow).

### 8. Optional — expose `POST /agent` on FastAPI

Not required if Streamlit + Loom is enough. If you want it on Render:

- Add `POST /agent` to Week 2 `main.py` that invokes the ADK agent
- Return `{ "answer", "steps": [{ "tool", "observation" }, ...] }`
- Keep `/ask` working

---

## Submission checklist (Path A)

Before considering the assignment done:

- [ ] Stack named: **Google ADK** (preferred) or LangGraph with coach approval
- [ ] Multi-step task completes with at least **one real tool call**
- [ ] **Think → Act → Observe** visible in logs or Loom
- [ ] Loop is **bounded** (max iterations set)
- [ ] **Streamlit UI** runs and demos the agent (screenshot or Loom for Maven)
- [ ] One-liner explains **agent vs workflow** for your job
- [ ] No secrets in screenshots, Loom, or Maven posts
- [ ] Did **not** submit unchanged Demo 1/2/3

---

## Path B — stretch goals (optional)

Only after Path A is done. Pick **one**:

| Stretch | What |
|---------|------|
| Human-in-the-loop | Pause before consequential action (email, DB write) |
| Multi-agent / A2A | Router + specialists (see Demo 1 / Demo 3) — only if roles truly separate |
| MCP tool | Supabase or other MCP server (see Demo 2) |
| LangGraph mirror | Rebuild same job in `langgraph-multi-agent-systems` |
| Prompt-injection drill | Malicious doc/instruction + show defense |

---

## Suggested build order (day-by-day)

| Day | Task |
|-----|------|
| 1 | Run Demo 1; read `demo1_routing.py`; get `GOOGLE_API_KEY`; read `rag-summary.md` |
| 2 | Create `zearn_support_agent.py` with `search_docs` tool (HTTP or import) |
| 3 | Prove one Think/Act/Observe run; cap iterations |
| 4 | Streamlit UI + screenshot/Loom |
| 5 | Write one-liner; submit to Maven/WhatsApp |

---

## Agent vs workflow — choose on purpose

| Shape | Example |
|-------|---------|
| **Workflow** | Every run: `search_docs` → answer (same order, no real choice) |
| **Agent** | Model may skip search for meta questions, search twice with different queries, or ask for clarification first |

Use the simplest shape that fits the job. Path A accepts a focused single-agent + one tool.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Gemini / ADK auth error | Set `GOOGLE_API_KEY` in `.env`; restart shell |
| Model never calls tool | Tighten tool description; use a question that requires doc lookup |
| Infinite loop / high cost | Lower step limit to 8–12; log every step |
| Tool errors crash run | Return errors as observations, don't raise |
| Streamlit can't reach agent | Check API URL in sidebar/env |
| Week 2 retrieval empty | Run `POST /ingest`; confirm Pinecone env vars |
| Render OOM | Week 2 rerank disabled on 512MB — use `/retrieve` not full local rerank stack |

**Golden rule:** Copy the full error into Cursor/Claude Code: *"I got this error, please fix it and explain what happened in simple terms."*

---

## Key references

| Resource | Location |
|----------|----------|
| ADK sample (this folder) | `demo1_routing.py`, `streamlit_app.py`, `README.md` |
| Week 2 RAG handoff | `../ai-engineering-bootcamp-v2/week-2/rag-vector-databases/rag-summary.md` |
| Week 2 scrapers handoff | `../ai-engineering-bootcamp-v2/week-2/scrapers/scrapers-summary.md` |
| Week 2 golden eval | `../ai-engineering-bootcamp-v2/week-2/rag-vector-databases/golden_set.json` |
| LangGraph alternative | `../langgraph-multi-agent-systems/` |
| Google ADK docs | https://google.github.io/adk-docs/ |
| Gemini API key | https://aistudio.google.com/apikey |

---

## What success looks like

```
User: "How do I add students without a class code?"
  → Think: need to search Zearn docs
  → Act:  search_docs("add students without class code")
  → Observe: chunks from add-students-to-your-class
  → Think: need alternate path for existing accounts
  → Act:  search_docs("class code existing Zearn account")
  → Observe: more chunks
  → Answer: grounded response with both paths
```

Week 2 `/ask` often misses the class-code path in one retrieval pass. A well-instructed agent can search twice — that is the point of Week 3.

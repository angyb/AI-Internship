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
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment** → add:
   - `OPENAI_API_KEY`
   - `PINECONE_API_KEY`
   - `PINECONE_INDEX_NAME`
   - `PINECONE_HOST` (hostname only, no `https://`)
5. Deploy, then open your service URL (for example `https://your-app.onrender.com/docs`).

If you see `Could not import module "main"`, the **Root Directory** is wrong or empty.

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

## Cross-encoder reranking (local, free)

After hybrid/dense retrieval, a **local cross-encoder** re-scores the top candidates and keeps the best `k` for the LLM context. No Cohere or other paid rerank API — runs on CPU via [sentence-transformers](https://www.sbert.net/docs/pretrained_cross-encoder.html).

- **Default model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80MB, downloaded on first startup)
- **Flow:** fetch `RERANK_CANDIDATES` (default 20) → cross-encoder score → per-document cap → final `k=5`
- **Render:** model loads at startup (same lifespan as BM25 rebuild); first deploy build installs PyTorch CPU + sentence-transformers
- **Disable:** `RERANK_ENABLED=false` or `"use_rerank": false` on `POST /retrieve`
- **Override model:** `RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`

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


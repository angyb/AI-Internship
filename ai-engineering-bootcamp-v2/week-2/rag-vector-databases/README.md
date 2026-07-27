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

## Golden-set evaluation

Like Part 7 of `rag_vector_databases_live_session.ipynb`, but against your Pinecone pipeline.

**Files:**
- `golden_set.json` — 5 questions with human-written reference answers and expected `document_id`s
- `eval_golden.py` — runs retrieval + `/ask` generation, then scores with RAGAS

**Metrics tracked:**

| Metric | What it measures |
|--------|------------------|
| `retrieval_hit` | Did top-k chunks include the expected `document_id`? (binary) |
| `faithfulness` | Is the answer supported by retrieved context? (RAGAS) |
| `answer_correctness` | How close is the answer to the reference? (RAGAS — your **correctness** score) |

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate
pip install -r requirements-dev.txt
python eval_golden.py
```

The script upserts the Northwind handbook before eval (so questions 2–3 can hit). Skip with `--skip-northwind-upsert` if already indexed.

**Assignment screenshot:** terminal output showing the per-question table with all three metrics and the averages block at the bottom.

## 📝 License

This notebook is part of The AI Internship curriculum.


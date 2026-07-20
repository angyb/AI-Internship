# Week 1 — `/ask` Demo (5 stages)

Build a typed LLM endpoint step by step. Each stage is a standalone FastAPI app you can run and compare.

## Setup

From this `week-1` folder:

```bash
cd ai-engineering-bootcamp-v2/week-1
cp .env.example .env
```

Open `.env` and add your key (no spaces around `=`):

```bash
OPENAI_API_KEY=sk-...
```

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Prefer Python 3.10+ (3.13 works well). On macOS with Homebrew, you can use:

```bash
/opt/homebrew/bin/python3 -m venv .venv
```

## Local run

Activate the venv first (`source .venv/bin/activate`).

### API (Terminal 1)

Run **one** stage at a time (only one process can use port 8000):

```bash
# Stage 1–4 examples:
uvicorn serve_stage1:app --host 127.0.0.1 --port 8000 --reload
uvicorn serve_stage2:app --host 127.0.0.1 --port 8000 --reload
uvicorn serve_stage3:app --host 127.0.0.1 --port 8000 --reload
uvicorn serve_stage4:app --host 127.0.0.1 --port 8000 --reload

# Stage 5 / full system (same app as main.py):
uvicorn serve_stage5:app --host 127.0.0.1 --port 8000 --reload
# or:
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open the interactive docs:

```text
http://127.0.0.1:8000/docs
```

### Streamlit demo page (Terminal 2)

```bash
streamlit run demo_page.py
```

Open:

```text
http://localhost:8501
```

Set **API base URL** to `http://127.0.0.1:8000` and keep the matching stage server running in Terminal 1.

### Smoke-test all stages

Requires `.venv` and a valid `OPENAI_API_KEY`:

```bash
python test_all_stages.py
```

## Deploy (Render)

Deploy the Stage 5 / full API (`main.py`) as a Render **Web Service** from this GitHub repo.

1. Push your code to GitHub (do **not** commit `.env`).
2. In [Render](https://render.com): **New → Web Service** → connect the repo.
3. Settings:
   - **Root Directory:** `ai-engineering-bootcamp-v2/week-1`  
     (required — there is no `main.py` at the repo root)
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment** → add:
   - `OPENAI_API_KEY` = your key
5. Deploy, then open your service URL (for example `https://your-app.onrender.com/docs`).

If you see `Could not import module "main"`, the Root Directory is wrong or empty.

## Curl

Local Stage 5 / full system:

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is RAG in one sentence?"}'
```

Choose model + see `cost_usd`:

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is chunking?", "model": "gpt-4o-mini"}'
```

Trigger the Stage 3+ guardrail demo (`force_bad`), then turn it off:

```bash
# Force a bad first response (validation fails, then retry succeeds)
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is 2 + 2?", "force_bad": true}'

# Normal call again
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is 2 + 2?", "force_bad": false}'
```

Against a Render deploy, swap the host:

```bash
curl -s -X POST https://your-app.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is RAG in one sentence?"}'
```

## Demo stages

| Stage | File | What you learn |
|-------|------|----------------|
| 1 | `serve_stage1.py` | Bare `/ask` — string answer + `tokens_used` |
| 2 | `serve_stage2.py` | Structured output via Pydantic + `completions.parse` |
| 3 | `serve_stage3.py` | Validation guardrail + retry (`force_bad` demo knob) |
| 4 | `serve_stage4.py` | Per-request `model` override + `latency_ms` |
| 5 | `serve_stage5.py` / `main.py` | Full system + `cost_usd` readout |

Default model for Stage 5 / `main.py` is `gpt-4o` (override with `"model"` in the request body).

## Project layout

```
week-1/
├── main.py              # Full system (stages 1–5 combined)
├── serve_stage1.py … serve_stage5.py
├── demo_page.py         # Streamlit test UI
├── test_all_stages.py   # Automated stage smoke tests
├── requirements.txt
├── .env.example
└── .gitignore
```

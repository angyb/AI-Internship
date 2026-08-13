# Week 4 TRACE — Path A Submission (Zearn Agent Capstone)

## Top failure

**Missing citation on web fallback** — when the agent used `google_search_agent`, the final answer often had no markdown `[title](url)` source link (4/18 traces: q07, q08, q09, q17).

## Checks codified (`eval_agent.py`)

| Check | What it catches |
|-------|-----------------|
| `used_tool` | Answer without `search_zearn_doc` / `google_search_agent` |
| `citation_present` | Corpus or web answer missing markdown citation link |
| `fallback_banner` | `FALLBACK_PREFIX` mismatch with web tool usage |
| `outcome_appropriate` | Wrong refuse / answer / web routing vs `expected_outcome` |
| `length_budget` | Answer over 2500 characters |

## Fix shipped

Tightened `AGENT_INSTRUCTION` in [`zearn_faq_bot/constants.py`](../zearn_faq_bot/constants.py):

- Every non-refusal answer **must** include at least one markdown link.
- Web fallback answers **must** include a markdown link to a URL from search results.

## Metric move (before → after)

| Check | Before | After | Delta |
|-------|--------|-------|-------|
| **citation_present** | **77.8% (14/18)** | **100% (18/18)** | **+22.2 pp** |
| used_tool | 94.4% | 100% | +5.6 pp |
| all checks pass | 61.1% (11/18) | 83.3% (15/18) | +22.2 pp |

Artifacts:

- Baseline traces: `zearn_agent_traces_before.jsonl`
- Current traces: `zearn_agent_traces.jsonl`
- Scores: `eval_before.json`, `eval_after.json`
- Taxonomy: `failure_taxonomy.md`
- Open coding: `open_coding.csv`

## How to run

```bash
cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
source .venv/bin/activate

# Capture traces (requires GOOGLE_API_KEY)
python agent_trace.py

# Run checks
python eval_agent.py --output traces/eval_after.json

# API + Streamlit
uvicorn main:app --host 127.0.0.1 --port 8000
streamlit run demo_page.py   # Agent Checks tab → POST /eval-agent
```

Extension: open Ask Z-Bot → **Trace** tab → **Run checks** (calls `POST /eval-agent` via background.js).

## Screenshots for Maven

1. Streamlit **Agent Checks** tab showing pass rates and before/after table.
2. Same view highlighting `citation_present` 77.8% → 100%.

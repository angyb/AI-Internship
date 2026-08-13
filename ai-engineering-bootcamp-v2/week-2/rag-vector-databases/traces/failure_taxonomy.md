# Zearn Agent Failure Taxonomy (Week 4 TRACE — Path A)

Open-coded from **18** real ADK agent traces in `zearn_agent_traces.jsonl` (baseline capture, pre-fix).

## Failure categories (ranked by frequency × impact)

| Rank | Category | Definition | Count | Example trace IDs |
|------|----------|------------|-------|-------------------|
| 1 | **Missing citation on web fallback** | Agent used `google_search_agent` but final answer has no markdown `[title](url)` link | 4 | q07, q08, q09, q17 |
| 2 | **Wrong outcome for off-topic question** | Expected `refuse` but agent returned `answer` or `web` | 3 | q09, q10, q13 |
| 3 | **Verbosity / length budget** | Final answer exceeds 2500 characters or dumps long web text | 2 | q05, q09 |
| 4 | **Answered without tool use** | Final answer with no `search_zearn_doc` / `google_search_agent` Act step | 1 | q13 |
| 5 | **Wrong refusal** | Expected `answer` from corpus but got `REFUSAL_MESSAGE` | 0 | — |

## Top target for fix

**Missing citation on web fallback** — highest frequency (4/18), directly tied to `AGENT_INSTRUCTION`, and fixable with a prompt rule requiring markdown source links whenever `google_search_agent` is used.

Codified check: `check_citation_present` in `eval_agent.py`.

Secondary checks tied to other categories:

- `check_outcome_appropriate` — off-topic routing (q09, q10, q13)
- `check_used_tool` — no-tool answers (q13)
- `check_length_budget` — verbosity (q05, q09)
- `check_fallback_banner` — already 100% pass (no change needed)

## Baseline check pass rates (eval_before.json)

| Check | Pass rate |
|-------|-----------|
| used_tool | 94.4% (17/18) |
| citation_present | **77.8% (14/18)** ← fix target |
| fallback_banner | 100% (18/18) |
| outcome_appropriate | 83.3% (15/18) |
| length_budget | 88.9% (16/18) |
| All checks | 61.1% (11/18) |

## Open-coding notes (sample)

- **q07 / q08 / q17**: Correctly escalated to web search; answer content reasonable but **no clickable Sources link**.
- **q09**: Off-topic (sourdough) — should refuse; agent web-searched and returned a long uncited answer.
- **q10**: Stock ticker — not in Zearn docs; agent answered from a weak corpus hit instead of refusing.
- **q13**: Prompt injection — agent replied without calling any tool (policy violation).
- **q05**: Good corpus answer but slightly over length budget.

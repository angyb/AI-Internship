# Adding a tool to the Zearn Support Agent

Use this when building a **new ADK tool** for `zearn_support_agent`. The Chrome
extension and Streamlit UI call `POST /agent` only — new tools appear after API
redeploy with **no extension changes**.

Reference implementation: [`tools/search_zearn_doc.py`](tools/search_zearn_doc.py)  
Agent wiring: [`agent.py`](agent.py)  
Instructions / refusal policy: [`constants.py`](constants.py)

---

## Workflow

1. **Create** `tools/<snake_name>.py`  
   - Use a real snake_case name (e.g. `lookup_roster_limit.py`).  
   - Do **not** create a file literally named `my_tool.py` unless that is the chosen name.
2. **Implement** a plain Python function (ADK tool). Give it a clear docstring —
   ADK uses the docstring (and type hints) as the tool description/schema for Gemini.
3. **Register** the function on the agent in [`agent.py`](agent.py):

   ```python
   from zearn_faq_bot.tools.<snake_name> import <fn_name>

   zearn_agent = Agent(
       ...
       tools=[search_zearn_doc, <fn_name>, AgentTool(agent=google_search_agent)],
   )
   ```

4. **Export** from [`tools/__init__.py`](tools/__init__.py) if other modules import the package exports.
5. **Update** `AGENT_INSTRUCTION` in [`constants.py`](constants.py) only when the model
   must learn *when* to call the new tool (otherwise it may ignore it).
6. **Redeploy** the Render API service `week-2-rag-api` (root dir
   `ai-engineering-bootcamp-v2/week-2/rag-vector-databases`).
7. **Verify** with `POST /agent`, Streamlit, or Ask Z-Bot — confirm Think/Act/Observe
   shows the new tool name.

Sub-agents (like Google Search) live under `sub_agents/` and are wrapped with
`AgentTool`, not under `tools/`.

---

## Tool shape (match existing style)

```python
"""short_name — one-line job."""

from __future__ import annotations


def my_capability(query: str) -> dict:
    """What the agent should use this for (shown to the model).

    Args:
        query: ...

    Returns:
        Dict the Observe step can summarize (prefer JSON-serializable).
    """
    try:
        # ... work ...
        return {"ok": True, "result": "..."}
    except Exception as exc:
        return {"error": str(exc), "ok": False}
```

Prefer returning structured `dict`s (like `search_zearn_doc`) so the runner’s
Observe logging stays readable.

---

## Checklist

- [ ] File under `tools/<snake_name>.py` with docstring + type hints
- [ ] Registered in `agent.py`
- [ ] `__init__.py` updated if needed
- [ ] `AGENT_INSTRUCTION` updated only if routing requires it
- [ ] No secrets in tool code
- [ ] User told to redeploy `week-2-rag-api`
- [ ] Manual `/agent` test suggested

---

## Related

- Plan note: [`../chrome-extension-plan.md`](../chrome-extension-plan.md) (extension consumes `/agent` only)
- Cursor skill: `.cursor/skills/add-zearn-agent-tool/`
- Cursor rule: `.cursor/rules/zearn-agent-tools.mdc`

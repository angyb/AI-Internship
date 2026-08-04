"""ADK runner and Think / Act / Observe step logging for zearn_support_agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from zearn_faq_bot.agent import zearn_agent
from zearn_faq_bot.constants import MAX_LLM_CALLS, REFUSAL_MESSAGE


def _fallback_answer(_steps: list[dict[str, Any]]) -> str:
    """Use when the ADK loop ends without a captured final text response."""
    return REFUSAL_MESSAGE


def _extract_text_from_part(part: Any) -> str:
    text = getattr(part, "text", None)
    return text.strip() if text and text.strip() else ""


def _classify_step(part: Any, author: str) -> dict[str, Any] | None:
    fc = getattr(part, "function_call", None)
    fr = getattr(part, "function_response", None)
    text = getattr(part, "text", None)

    if fc:
        return {
            "phase": "Act",
            "author": author,
            "tool": fc.name,
            "args": dict(fc.args) if fc.args else {},
        }
    if fr:
        result = fr.response
        if isinstance(result, dict):
            summary = {
                "chunk_count": result.get("chunk_count", 0),
                "document_ids": [
                    c.get("document_id", "") for c in result.get("chunks", [])
                ],
                "error": result.get("error"),
            }
            display = json.dumps(summary, indent=2)
        else:
            display = str(result)[:800] if result else ""
        return {
            "phase": "Observe",
            "author": author,
            "tool": fr.name,
            "result": display,
        }
    if text and text.strip():
        return {"phase": "Think", "author": author, "text": text.strip()}
    return None


async def run_zearn_agent_async(question: str) -> tuple[str, list[dict[str, Any]]]:
    service = InMemorySessionService()
    runner = Runner(agent=zearn_agent, app_name="zearn_support", session_service=service)
    session = await service.create_session(app_name="zearn_support", user_id="user1")
    content = types.Content(role="user", parts=[types.Part(text=question)])
    run_config = RunConfig(max_llm_calls=MAX_LLM_CALLS)

    steps: list[dict[str, Any]] = []
    final = ""
    last_think_text = ""

    async for event in runner.run_async(
        user_id="user1",
        session_id=session.id,
        new_message=content,
        run_config=run_config,
    ):
        author = getattr(event, "author", "unknown")
        if event.content and event.content.parts:
            for part in event.content.parts:
                step = _classify_step(part, author)
                if step:
                    steps.append(step)
                    if step["phase"] == "Think":
                        last_think_text = step["text"]
                text = _extract_text_from_part(part)
                if text and event.is_final_response():
                    final = text

    if not final:
        final = last_think_text
    if not final:
        final = _fallback_answer(steps)

    return final, steps


def run_zearn_agent(question: str) -> tuple[str, list[dict[str, Any]]]:
    return asyncio.run(run_zearn_agent_async(question))

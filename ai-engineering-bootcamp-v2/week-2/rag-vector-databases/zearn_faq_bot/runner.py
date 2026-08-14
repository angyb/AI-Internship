"""ADK runner and Think / Act / Observe step logging for zearn_support_agent."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from google.adk.agents.run_config import RunConfig
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session
from google.genai import types

from zearn_faq_bot.agent import zearn_agent
from zearn_faq_bot.constants import MAX_LLM_CALLS, REFUSAL_MESSAGE
from zearn_faq_bot.formatting import strip_duplicate_inline_sources


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
            sources: list[dict[str, str]] = []
            seen: set[str] = set()
            for chunk in result.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                title = str(chunk.get("title") or chunk.get("document_id") or "").strip()
                source_url = str(chunk.get("source_url") or "").strip()
                document_id = str(chunk.get("document_id") or "").strip()
                key = source_url or document_id or title
                if not key or key in seen:
                    continue
                seen.add(key)
                sources.append(
                    {
                        "title": title,
                        "source_url": source_url,
                        "document_id": document_id,
                    }
                )
            summary = {
                "chunk_count": result.get("chunk_count", 0),
                "document_ids": [
                    c.get("document_id", "") for c in result.get("chunks", [])
                ],
                "sources": sources,
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


async def _seed_history(
    service: InMemorySessionService,
    session: Session,
    history: list[dict[str, Any]] | None,
) -> None:
    """Replay prior turns into the ADK session so the agent has conversation memory.

    ``history`` is a list of ``{"role": "user"|"assistant", "content": str}`` in
    chronological order (excluding the new question). User turns are stored with
    role ``user``; assistant turns with role ``model`` authored by the agent.
    """
    if not history:
        return
    for turn in history:
        role = str((turn or {}).get("role") or "").lower()
        content_text = str((turn or {}).get("content") or "").strip()
        if not content_text:
            continue
        if role in ("assistant", "model", "agent"):
            genai_role = "model"
            author = zearn_agent.name
        else:
            genai_role = "user"
            author = "user"
        event = Event(
            invocation_id=uuid.uuid4().hex,
            author=author,
            content=types.Content(
                role=genai_role, parts=[types.Part(text=content_text)]
            ),
        )
        await service.append_event(session, event)


def _usage_from_event(event: Any, current: dict[str, int]) -> dict[str, int]:
    """Track the latest turn's token usage from Gemini ``usage_metadata``.

    The prompt token count of the most recent turn already includes the seeded
    history, so the max ``total_token_count`` seen is our running context size.
    """
    usage = getattr(event, "usage_metadata", None)
    if not usage:
        return current
    prompt = getattr(usage, "prompt_token_count", None) or 0
    output = getattr(usage, "candidates_token_count", None) or 0
    total = getattr(usage, "total_token_count", None) or (prompt + output)
    if total >= current.get("total_tokens", 0):
        return {"prompt_tokens": prompt, "output_tokens": output, "total_tokens": total}
    return current


def _google_search_tool_name(name: str | None) -> bool:
    tool = (name or "").lower()
    return tool in ("google_search_agent", "google_search")


def _google_search_author(author: str | None) -> bool:
    return "google_search" in (author or "").lower()


async def run_zearn_agent_async(
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    from timing import record_event
    from zearn_faq_bot.tools.search_zearn_doc import reset_search_call_count

    reset_search_call_count()
    service = InMemorySessionService()
    runner = Runner(agent=zearn_agent, app_name="zearn_support", session_service=service)
    session = await service.create_session(app_name="zearn_support", user_id="user1")
    await _seed_history(service, session, history)
    content = types.Content(role="user", parts=[types.Part(text=question)])
    run_config = RunConfig(max_llm_calls=MAX_LLM_CALLS)

    steps: list[dict[str, Any]] = []
    final = ""
    last_think_text = ""
    usage: dict[str, int] = {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    last_event_time = time.perf_counter()
    in_google_search = False

    async for event in runner.run_async(
        user_id="user1",
        session_id=session.id,
        new_message=content,
        run_config=run_config,
    ):
        now = time.perf_counter()
        delta_ms = (now - last_event_time) * 1000
        if in_google_search:
            record_event("google_search_agent", delta_ms)
        else:
            record_event("gemini_llm", delta_ms)
        last_event_time = now

        usage = _usage_from_event(event, usage)
        author = getattr(event, "author", "unknown")
        if _google_search_author(author):
            in_google_search = True
        if event.content and event.content.parts:
            for part in event.content.parts:
                fc = getattr(part, "function_call", None)
                fr = getattr(part, "function_response", None)
                if fc and _google_search_tool_name(fc.name):
                    in_google_search = True
                if fr and _google_search_tool_name(fr.name):
                    in_google_search = False

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

    from zearn_faq_bot.tools.search_zearn_doc import get_search_call_count

    usage["search_call_count"] = get_search_call_count()
    return strip_duplicate_inline_sources(final), steps, usage


def run_zearn_agent(
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    return asyncio.run(run_zearn_agent_async(question, history))

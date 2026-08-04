"""
Zearn support agent — Google ADK with search_zearn_doc backed by local retrieve_context().

Used by POST /agent on the Week 2 RAG API (same process — no HTTP loopback on Render).

Run:
    python zearn_support_agent.py "What causes a Tower Alert and what is its purpose?"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import AgentTool, google_search
from google.genai import types

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
MAX_LLM_CALLS = 15
CHUNK_TEXT_LIMIT = 500

REFUSAL_MESSAGE = (
    "I couldn't find that in the Zearn documentation corpus. "
    "Try rephrasing your question, or contact Zearn support for help."
)

FALLBACK_PREFIX = (
    "This wasn't found in Zearn documentation; sourced from the web."
)

GOOGLE_SEARCH_INSTRUCTION = (
    "You are a Google search sub-agent. "
    "Search the web for current information relevant to the user's question. "
    "Always cite source URLs in your answer."
)

AGENT_INSTRUCTION = (
    "You are a Zearn support agent. "
    "For factual Zearn questions, call search_zearn_doc before answering. "
    "Use only retrieved content from search_zearn_doc when it answers the question. "
    "If the first search is insufficient, refine your query and search again. "
    "Cite document titles when possible. "
    "If search_zearn_doc returns no chunks, returns an error, or the retrieved chunks "
    "clearly do not answer the question, call google_search_agent for a web fallback. "
    f"When you use google_search_agent, start your final answer with exactly: \"{FALLBACK_PREFIX}\" "
    "Use only search_zearn_doc or google_search_agent; do not answer from memory. "
    f"If both fail, respond with exactly: \"{REFUSAL_MESSAGE}\" "
    "Always end with a clear, complete user-facing answer."
)


def _format_chunks_from_retrieved(chunks: list[Any]) -> dict:
    """Turn RetrievedChunk objects into the search_zearn_doc tool response shape."""
    out = []
    for chunk in chunks:
        text = chunk.text
        if len(text) > CHUNK_TEXT_LIMIT:
            text = text[:CHUNK_TEXT_LIMIT] + "..."
        out.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "text": text,
                "source": chunk.source,
            }
        )
    return {"chunk_count": len(out), "chunks": out}


def search_zearn_doc(question: str) -> dict:
    """Search the Zearn knowledge base for relevant documentation chunks.

    Use this tool before answering factual questions about Zearn Math,
    teacher and admin workflows, Tower Alerts, rosters, accounts, or product features.

    Args:
        question: A search query describing what you need from the docs.

    Returns:
        Dict with chunk_count and chunks (chunk_id, document_id, text, source).
    """
    try:
        from main import retrieve_context

        chunks, _context, _chunk_ids, _sources = retrieve_context(question)
    except KeyError as exc:
        return {
            "error": f"Missing required environment variable: {exc.args[0]}",
            "chunks": [],
            "chunk_count": 0,
        }
    except Exception as exc:
        return {
            "error": f"Retrieval failed: {exc}",
            "chunks": [],
            "chunk_count": 0,
        }

    if not chunks:
        return {"chunk_count": 0, "chunks": []}

    return _format_chunks_from_retrieved(chunks)


google_search_agent = Agent(
    name="google_search_agent",
    model=MODEL,
    instruction=GOOGLE_SEARCH_INSTRUCTION,
    tools=[google_search],
)

zearn_agent = Agent(
    name="zearn_support_agent",
    model=MODEL,
    instruction=AGENT_INSTRUCTION,
    tools=[search_zearn_doc, AgentTool(agent=google_search_agent)],
)


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


def main() -> None:
    question = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "What causes a Tower Alert and what is its purpose?"
    )
    if not os.getenv("GOOGLE_API_KEY"):
        print("ERROR: Set GOOGLE_API_KEY in .env")
        sys.exit(1)

    print(f"Question: {question}\n")
    answer, steps = run_zearn_agent(question)
    for i, step in enumerate(steps, start=1):
        print(f"[{i}] {step.get('phase')} — {step}")
    print("\nFINAL ANSWER\n", answer)


if __name__ == "__main__":
    main()

"""
Zearn support agent — Google ADK agent with real search_docs tool (Week 2 retrieval).

Run:
    python zearn_support_agent.py "What causes a Tower Alert and what is its purpose?"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
MAX_LLM_CALLS = 10
RAG_API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
CHUNK_TEXT_LIMIT = 500

REFUSAL_MESSAGE = (
    "I couldn't find that in the Zearn documentation corpus. "
    "Try rephrasing your question, or contact Zearn support for help."
)

AGENT_INSTRUCTION = (
    "You are a Zearn teacher support agent. "
    "For factual Zearn questions, call search_docs before answering. "
    "Use only retrieved content. If the first search is insufficient, "
    "refine your query and search again. Cite document titles when possible. "
    "If search_docs returns no chunks, or the retrieved chunks do not answer the question, "
    f"respond with exactly: \"{REFUSAL_MESSAGE}\" "
    "Never use outside knowledge. Always end with a clear, complete user-facing answer."
)


def search_docs(question: str) -> dict:
    """Search the Zearn knowledge base for relevant documentation chunks.

    Use this tool before answering factual questions about Zearn Math,
    teacher workflows, Tower Alerts, rosters, accounts, or product features.

    Args:
        question: A search query describing what you need from the docs.

    Returns:
        Dict with chunk_count and chunks (chunk_id, document_id, text, source).
    """
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{RAG_API_URL}/retrieve",
                json={"question": question},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        return {
            "error": f"Retrieval API returned {exc.response.status_code}",
            "chunks": [],
            "chunk_count": 0,
        }
    except httpx.RequestError as exc:
        return {
            "error": f"Could not reach retrieval API at {RAG_API_URL}: {exc}",
            "chunks": [],
            "chunk_count": 0,
        }

    chunks = []
    for chunk in data.get("chunks", []):
        text = chunk.get("text", "")
        if len(text) > CHUNK_TEXT_LIMIT:
            text = text[:CHUNK_TEXT_LIMIT] + "..."
        chunks.append(
            {
                "chunk_id": chunk.get("chunk_id", ""),
                "document_id": chunk.get("document_id", ""),
                "text": text,
                "source": chunk.get("source", ""),
            }
        )

    return {"chunk_count": len(chunks), "chunks": chunks}


zearn_agent = Agent(
    name="zearn_support_agent",
    model=MODEL,
    instruction=AGENT_INSTRUCTION,
    tools=[search_docs],
)


def _fallback_answer(_steps: list[dict[str, Any]]) -> str:
    """Use when the ADK loop ends without a captured final text response."""
    return REFUSAL_MESSAGE


def _extract_text_from_part(part: Any) -> str:
    text = getattr(part, "text", None)
    return text.strip() if text and text.strip() else ""


def _classify_step(part: Any, author: str) -> dict[str, Any] | None:
    """Map an ADK content part to a Think / Act / Observe step."""
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
    """Run the Zearn agent and return (final_answer, steps)."""
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
    """Synchronous wrapper for Streamlit and CLI."""
    return asyncio.run(run_zearn_agent_async(question))


def print_steps(steps: list[dict[str, Any]]) -> None:
    for i, step in enumerate(steps, start=1):
        phase = step["phase"]
        if phase == "Think":
            print(f"\n[{i}] THINK — {step['author']}")
            print(step["text"])
        elif phase == "Act":
            args = ", ".join(f"{k}={v!r}" for k, v in step.get("args", {}).items())
            print(f"\n[{i}] ACT — {step['author']} called {step['tool']}({args})")
        elif phase == "Observe":
            print(f"\n[{i}] OBSERVE — result from {step['tool']}")
            print(step.get("result", ""))


def main() -> None:
    question = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "What causes a Tower Alert and what is its purpose?"
    )
    if not os.getenv("GOOGLE_API_KEY"):
        print("ERROR: Set GOOGLE_API_KEY in .env")
        sys.exit(1)

    print(f"RAG API: {RAG_API_URL}")
    print(f"Question: {question}\n")
    print("=" * 60)

    answer, steps = run_zearn_agent(question)
    print_steps(steps)

    print("\n" + "=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()

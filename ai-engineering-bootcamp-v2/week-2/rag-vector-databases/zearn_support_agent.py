"""
Zearn support agent — thin shim over zearn_faq_bot for POST /agent and CLI.

Canonical package: zearn_faq_bot/ (tools, sub-agents, agent, runner).

Run:
    python zearn_support_agent.py "What causes a Tower Alert and what is its purpose?"
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from zearn_faq_bot.agent import zearn_agent
from zearn_faq_bot.constants import FALLBACK_PREFIX, REFUSAL_MESSAGE
from zearn_faq_bot.runner import run_zearn_agent, run_zearn_agent_async
from zearn_faq_bot.tools.search_zearn_doc import search_zearn_doc

load_dotenv()

__all__ = [
    "FALLBACK_PREFIX",
    "REFUSAL_MESSAGE",
    "run_zearn_agent",
    "run_zearn_agent_async",
    "search_zearn_doc",
    "zearn_agent",
]


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

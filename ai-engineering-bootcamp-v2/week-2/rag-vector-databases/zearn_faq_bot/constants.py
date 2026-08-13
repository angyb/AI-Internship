"""Shared constants and agent instructions for the Zearn support agent."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
MAX_LLM_CALLS = 15
CHUNK_TEXT_LIMIT = 800

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
    "When citing Zearn docs, use markdown links from each chunk's title and source_url, "
    "like: Source: [Boosts](https://help.zearn.org/...). "
    "If source_url is missing, cite the title only. Deduplicate sources. "
    "Every non-refusal final answer MUST include at least one markdown link "
    "([Title](url)) citing a Zearn doc or web source — never finish without a link. "
    "If search_zearn_doc returns no chunks, returns an error, or the retrieved chunks "
    "clearly do not answer the question, call google_search_agent for a web fallback. "
    f"When you use google_search_agent, start your final answer with exactly: \"{FALLBACK_PREFIX}\" "
    "and include at least one markdown link to a URL from the web search results "
    "(for example: Source: [Site Name](https://example.com)). "
    "Use only search_zearn_doc or google_search_agent; do not answer from memory. "
    f"If both fail, respond with exactly: \"{REFUSAL_MESSAGE}\" "
    "Always end with a clear, complete user-facing answer."
)

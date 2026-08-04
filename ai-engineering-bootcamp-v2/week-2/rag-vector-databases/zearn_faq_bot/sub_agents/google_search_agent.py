"""google_search_agent — ADK sub-agent that owns the google_search tool."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import google_search

from zearn_faq_bot.constants import GOOGLE_SEARCH_INSTRUCTION, MODEL

google_search_agent = Agent(
    name="google_search_agent",
    model=MODEL,
    instruction=GOOGLE_SEARCH_INSTRUCTION,
    tools=[google_search],
)

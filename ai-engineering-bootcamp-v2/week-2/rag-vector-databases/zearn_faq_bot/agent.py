"""Main zearn_support_agent wiring (RAG tool + Google Search sub-agent)."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import AgentTool

from zearn_faq_bot.constants import AGENT_INSTRUCTION, MODEL
from zearn_faq_bot.sub_agents.google_search_agent import google_search_agent
from zearn_faq_bot.tools.lookup_state_standard import lookup_state_standard
from zearn_faq_bot.tools.search_zearn_doc import search_zearn_doc

zearn_agent = Agent(
    name="zearn_support_agent",
    model=MODEL,
    instruction=AGENT_INSTRUCTION,
    tools=[
        lookup_state_standard,
        search_zearn_doc,
        AgentTool(agent=google_search_agent),
    ],
)

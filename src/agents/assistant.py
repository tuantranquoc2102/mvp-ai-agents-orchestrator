"""General Assistant — catch-all (any tool, summarization)."""
from .base import ALL_TOOLS, Agent, register_agent

AGENT = register_agent(Agent(
    name="assistant",
    role="General Assistant",
    description="Handles miscellaneous tasks and summarization.",
    allowed_tools=[ALL_TOOLS],
))

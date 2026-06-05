"""Chief Strategy Officer — market positioning."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="cso",
    role="Chief Strategy Officer",
    description="Frames market positioning and long-range strategy.",
    allowed_tools=["read_doc", "search_web"],
))

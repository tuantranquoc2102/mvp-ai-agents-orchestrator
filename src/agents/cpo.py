"""Chief Product Officer — product vision and roadmap."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="cpo",
    role="Chief Product Officer",
    description="Owns product vision, prioritization, and roadmap.",
    allowed_tools=["read_doc", "write_doc", "search_web"],
))

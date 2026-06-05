"""Solution Architect — cross-system design."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="sa",
    role="Solution Architect",
    description="Designs end-to-end solutions across business and technical layers.",
    allowed_tools=["read_doc", "write_doc", "read_code"],
))

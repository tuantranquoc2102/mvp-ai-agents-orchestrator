"""Research Specialist — prior art and unknowns."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="researcher",
    role="Research Specialist",
    description="Investigates prior art, libraries, and unknowns.",
    allowed_tools=["search_web", "read_doc", "write_doc"],
))

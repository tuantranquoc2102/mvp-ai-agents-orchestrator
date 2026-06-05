"""Software Architect — technical architecture + interfaces."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="architect",
    role="Software Architect",
    description="Defines technical architecture, components, and interfaces.",
    allowed_tools=["read_doc", "write_doc", "read_code"],
))

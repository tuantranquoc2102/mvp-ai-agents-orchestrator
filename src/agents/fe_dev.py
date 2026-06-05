"""Frontend Developer — UI components and client-side logic."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="fe_dev",
    role="Frontend Developer",
    description="Implements UI components and client-side logic.",
    allowed_tools=["read_code", "write_code", "run_tests"],
))

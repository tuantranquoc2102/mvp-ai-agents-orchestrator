"""Backend Developer — server-side implementation."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="be_dev",
    role="Backend Developer",
    description="Implements server-side code, APIs, and data access.",
    allowed_tools=["read_code", "write_code", "run_tests"],
))

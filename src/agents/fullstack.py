"""Fullstack Developer — spans frontend + backend."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="fullstack",
    role="Fullstack Developer",
    description="Spans frontend and backend implementation.",
    allowed_tools=["read_code", "write_code", "run_tests"],
))

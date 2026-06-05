"""Code Reviewer — read-only diff review."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="reviewer",
    role="Code Reviewer",
    description="Reviews diffs for correctness, style, and risk. Read-only.",
    allowed_tools=["read_code", "read_doc"],
))

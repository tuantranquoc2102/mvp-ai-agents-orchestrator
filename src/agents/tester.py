"""QA / Tester — writes and runs tests."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="tester",
    role="QA / Tester",
    description="Writes and runs tests, reports defects.",
    allowed_tools=["read_code", "write_code", "run_tests"],
))

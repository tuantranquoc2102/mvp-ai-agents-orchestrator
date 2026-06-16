"""Project Manager — milestone tracking + ticketing."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="pm",
    role="Project Manager",
    description="Breaks down deliverables, tracks milestones, coordinates agents.",
    allowed_tools=["read_doc", "write_doc", "create_ticket", "git_branch"],
))

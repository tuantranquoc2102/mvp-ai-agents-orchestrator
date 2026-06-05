"""Business Analyst — requirements elicitation."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="ba",
    role="Business Analyst",
    description="Elicits requirements and turns business needs into specs.",
    allowed_tools=["read_doc", "write_doc", "search_web"],
))

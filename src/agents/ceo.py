"""Chief Executive Officer — strategy approval."""
from .base import Agent, register_agent

AGENT = register_agent(Agent(
    name="ceo",
    role="Chief Executive Officer",
    description="Sets company-level direction and approves strategic initiatives.",
    allowed_tools=["read_doc", "search_web"],
))

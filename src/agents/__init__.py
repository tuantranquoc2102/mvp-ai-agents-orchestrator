"""Agent registry.

Every module in this package that defines an `AGENT` (Agent instance) is
auto-imported at startup; importing this package builds AGENT_REGISTRY as a
side effect. To add a new agent, drop a new file into this directory and
follow the pattern in any existing file (e.g. `architect.py`).
"""
from .base import (
    AGENT_REGISTRY,
    ALL_TOOLS,
    Agent,
    LLMAgentExecutor,
    get_agent,
    register_agent,
    use_llm_for_all_agents,
)

# Side-effect imports: each module calls register_agent() at module load.
from . import (  # noqa: F401  (imported for side effects)
    ceo, cpo, cso, pm, ba, sa, architect, researcher,
    be_dev, fe_dev, fullstack, reviewer, tester, assistant,
)

__all__ = [
    "AGENT_REGISTRY",
    "ALL_TOOLS",
    "Agent",
    "LLMAgentExecutor",
    "get_agent",
    "register_agent",
    "use_llm_for_all_agents",
]

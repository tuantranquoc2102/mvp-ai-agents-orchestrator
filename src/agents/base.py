"""Agent dataclass + registry helpers + LLM adapter.

An Agent is just data: a name, a role, an allowed-tool list, and a
default executor. The default executor returns a structured stub so the
orchestrator can be exercised without an LLM. `LLMAgentExecutor` adapts
any `LLMProvider` to the same signature, so swapping mock ↔ Claude CLI
is a one-line change at startup.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from src.llm.base import LLMProvider

# Sentinel meaning "any registered tool" (used by the assistant agent).
ALL_TOOLS = "*"

# Module-level registry. Each per-role module appends to it on import.
AGENT_REGISTRY: dict[str, "Agent"] = {}


@dataclass
class Agent:
    name: str
    role: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    system_prompt: str = ""
    # An overridable hook so tests / real LLMs can plug in.
    # Signature: (agent, instruction, inputs, context) -> output (any JSON-able).
    executor: Callable[..., Any] | None = None

    def can_use(self, tool_name: str | None) -> bool:
        if tool_name is None:
            return True
        if ALL_TOOLS in self.allowed_tools:
            return True
        return tool_name in self.allowed_tools

    def execute(
        self,
        instruction: str,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self.executor is not None:
            return self.executor(self, instruction, inputs, context)
        # Default mock — readable in demos / when no LLM is wired up.
        return {
            "agent": self.name,
            "role": self.role,
            "instruction": instruction,
            "summary": f"[{self.role}] completed: {instruction}",
            "inputs_seen": list(inputs.keys()),
        }


def register_agent(agent: Agent) -> Agent:
    """Add `agent` to the global registry. Returns the agent for chaining."""
    if agent.name in AGENT_REGISTRY:
        raise ValueError(f"duplicate agent name: {agent.name!r}")
    AGENT_REGISTRY[agent.name] = agent
    return agent


def get_agent(name: str) -> Agent:
    if name not in AGENT_REGISTRY:
        raise KeyError(
            f"Unknown agent: {name!r}. Known: {sorted(AGENT_REGISTRY)}"
        )
    return AGENT_REGISTRY[name]


# ---------------------------------------------------------------------------
# LLM adapter
# ---------------------------------------------------------------------------

def _truncate(value: Any, limit: int = 6000) -> str:
    try:
        text = json.dumps(value, indent=2, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > limit:
        text = text[:limit] + f"\n... (truncated, {len(text) - limit} more chars)"
    return text


def _build_system_prompt(agent: Agent) -> str:
    return (
        f"You are the {agent.role} ({agent.name}) in a multi-agent workflow.\n"
        f"{agent.description}\n\n"
        "Behavior rules:\n"
        "- Execute the user's task immediately; do NOT ask clarifying questions.\n"
        "- Respond in plain text or markdown, under ~400 words.\n"
        "- Be specific; cite file paths or identifiers from the user's inputs.\n"
        "- Output ONLY the analysis content — no preamble like "
        "'I'll help with that' or 'Here is my response'."
    )


def _build_user_prompt(instruction: str, inputs: dict[str, Any]) -> str:
    parts = [instruction or "(produce your best general analysis)"]
    if inputs:
        parts.append("\nInputs from prior workflow steps (JSON):")
        parts.append(_truncate(inputs))
    return "\n".join(parts)


class LLMAgentExecutor:
    """Adapts an `LLMProvider` to the `Agent.executor` callable signature.

    One instance can drive every agent in the registry — they all share the
    same provider but get their own role-specific system prompt.
    """

    def __init__(self, provider: LLMProvider, *, timeout: float = 300.0) -> None:
        self.provider = provider
        self.timeout = timeout

    def __call__(
        self,
        agent: Agent,
        instruction: str,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        system = _build_system_prompt(agent)
        user = _build_user_prompt(instruction, inputs)
        summary = self.provider.complete(system, user, timeout=self.timeout)
        return {
            "agent": agent.name,
            "role": agent.role,
            "summary": summary,
            "model": self.provider.name,
        }


def use_llm_for_all_agents(
    provider: LLMProvider,
    *,
    registry: dict[str, Agent] | None = None,
    timeout: float = 300.0,
) -> None:
    """Wire every agent in `registry` (default: AGENT_REGISTRY) to `provider`.

    Call once at startup. Replaces any prior executor.
    """
    target = registry if registry is not None else AGENT_REGISTRY
    executor = LLMAgentExecutor(provider, timeout=timeout)
    for agent in target.values():
        agent.executor = executor

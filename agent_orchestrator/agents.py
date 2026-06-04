"""Agent registry.

An Agent is just a named role with:
    - a short description / system-prompt fragment
    - a whitelist of tools it is allowed to invoke
    - an `execute()` hook (here: a deterministic mock for the MVP, or the
      Claude Code subscription CLI via `claude_code_executor`)

Two executors are shipped:
    * the default mock (returns a structured stub — great for tests)
    * `claude_code_executor` which shells out to the `claude` CLI in
      print mode (`claude -p`). It uses whatever the user is logged in
      with — i.e. the Claude Code subscription, NOT an API key.

Call `use_claude_code_for_all_agents()` once at startup to wire every
agent in AGENT_REGISTRY to the real LLM.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

# Tool name constants kept loose (just strings) to avoid a circular import
# with tools.py.  tools.py owns the canonical handlers.
ALL_TOOLS = "*"  # sentinel meaning "any registered tool"


@dataclass
class Agent:
    name: str
    role: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    system_prompt: str = ""
    # An overridable hook so tests / real LLMs can plug in.
    # Signature: (agent, instruction, inputs, context) -> output (any JSON-able)
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
        # Default mock: produce a structured "thought" so demos are readable.
        return {
            "agent": self.name,
            "role": self.role,
            "instruction": instruction,
            "summary": f"[{self.role}] completed: {instruction}",
            "inputs_seen": list(inputs.keys()),
        }


def _agent(
    name: str,
    role: str,
    description: str,
    allowed_tools: list[str],
    system_prompt: str = "",
) -> Agent:
    return Agent(
        name=name,
        role=role,
        description=description,
        allowed_tools=allowed_tools,
        system_prompt=system_prompt or f"You are a {role}. {description}",
    )


# ---------------------------------------------------------------------------
# Registered agents.  Permissions follow least-privilege: writers can write,
# reviewers can only read.
# ---------------------------------------------------------------------------
AGENT_REGISTRY: dict[str, Agent] = {
    a.name: a
    for a in [
        _agent(
            "ceo",
            "Chief Executive Officer",
            "Sets company-level direction and approves strategic initiatives.",
            allowed_tools=["read_doc", "search_web"],
        ),
        _agent(
            "cpo",
            "Chief Product Officer",
            "Owns product vision, prioritization, and roadmap.",
            allowed_tools=["read_doc", "write_doc", "search_web"],
        ),
        _agent(
            "cso",
            "Chief Strategy Officer",
            "Frames market positioning and long-range strategy.",
            allowed_tools=["read_doc", "search_web"],
        ),
        _agent(
            "pm",
            "Project Manager",
            "Breaks down deliverables, tracks milestones, coordinates agents.",
            allowed_tools=["read_doc", "write_doc", "create_ticket"],
        ),
        _agent(
            "ba",
            "Business Analyst",
            "Elicits requirements and turns business needs into specs.",
            allowed_tools=["read_doc", "write_doc", "search_web"],
        ),
        _agent(
            "sa",
            "Solution Architect",
            "Designs end-to-end solutions across business and technical layers.",
            allowed_tools=["read_doc", "write_doc", "read_code"],
        ),
        _agent(
            "architect",
            "Software Architect",
            "Defines technical architecture, components, and interfaces.",
            allowed_tools=["read_doc", "write_doc", "read_code"],
        ),
        _agent(
            "researcher",
            "Research Specialist",
            "Investigates prior art, libraries, and unknowns.",
            allowed_tools=["search_web", "read_doc", "write_doc"],
        ),
        _agent(
            "be_dev",
            "Backend Developer",
            "Implements server-side code, APIs, and data access.",
            allowed_tools=["read_code", "write_code", "run_tests"],
        ),
        _agent(
            "fe_dev",
            "Frontend Developer",
            "Implements UI components and client-side logic.",
            allowed_tools=["read_code", "write_code", "run_tests"],
        ),
        _agent(
            "fullstack",
            "Fullstack Developer",
            "Spans frontend and backend implementation.",
            allowed_tools=["read_code", "write_code", "run_tests"],
        ),
        _agent(
            "reviewer",
            "Code Reviewer",
            "Reviews diffs for correctness, style, and risk. Read-only.",
            allowed_tools=["read_code", "read_doc"],
        ),
        _agent(
            "tester",
            "QA / Tester",
            "Writes and runs tests, reports defects.",
            allowed_tools=["read_code", "write_code", "run_tests"],
        ),
        _agent(
            "assistant",
            "General Assistant",
            "Handles miscellaneous tasks and summarization.",
            allowed_tools=[ALL_TOOLS],
        ),
    ]
}


def get_agent(name: str) -> Agent:
    if name not in AGENT_REGISTRY:
        raise KeyError(f"Unknown agent: {name!r}. Known: {sorted(AGENT_REGISTRY)}")
    return AGENT_REGISTRY[name]


# ---------------------------------------------------------------------------
# Claude Code subscription executor
# ---------------------------------------------------------------------------
# Uses the local `claude` CLI in headless print mode. Auth comes from the
# user's existing Claude Code session (subscription) — no ANTHROPIC_API_KEY
# is read, set, or required.

class ClaudeCliNotFound(RuntimeError):
    """Raised when the `claude` executable is not on PATH."""


def _find_claude_cli() -> str:
    # `shutil.which` resolves `claude` -> `claude.cmd` on Windows automatically.
    exe = shutil.which("claude")
    if exe is None:
        raise ClaudeCliNotFound(
            "The `claude` CLI was not found on PATH. Install Claude Code "
            "and ensure `claude --version` works in your shell."
        )
    return exe


def _truncate_for_prompt(value: Any, limit: int = 6000) -> str:
    try:
        text = json.dumps(value, indent=2, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > limit:
        text = text[:limit] + f"\n... (truncated, {len(text) - limit} more chars)"
    return text


def _build_system_prompt(agent: "Agent") -> str:
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
        parts.append(_truncate_for_prompt(inputs))
    return "\n".join(parts)


def claude_code_executor(
    agent: "Agent",
    instruction: str,
    inputs: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Executor that runs each step through the local `claude` CLI.

    Uses Claude Code subscription auth (the same session used by the IDE/CLI).
    Spawns one `claude -p <prompt>` per step. Each call counts against your
    subscription quota.
    """
    exe = _find_claude_cli()
    system_prompt = _build_system_prompt(agent)
    user_prompt = _build_user_prompt(instruction, inputs)
    timeout = float(os.environ.get("AGENT_ORCH_CLAUDE_TIMEOUT", "300"))

    # `--print` (a.k.a. `-p`) runs headless and writes the final assistant
    # message to stdout. We pass:
    #   --system-prompt to replace the default (so CLAUDE.md / cwd / memory
    #       context don't leak into per-step responses)
    #   --tools ""      to disable tool use (the model must answer from the
    #       inputs we already supplied — no extra Read/Grep calls)
    # The user prompt goes through stdin so the variadic --tools flag can't
    # accidentally consume it as one of its values.
    result = subprocess.run(
        [exe, "--print",
         "--system-prompt", system_prompt,
         "--tools", ""],
        input=user_prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited with code {result.returncode}. "
            f"stderr: {(result.stderr or '').strip()[:500]}"
        )
    return {
        "agent": agent.name,
        "role": agent.role,
        "summary": (result.stdout or "").strip(),
        "model": "claude-code-subscription",
    }


def use_claude_code_for_all_agents(
    registry: dict[str, Agent] | None = None,
) -> None:
    """Wire every agent in `registry` (default: AGENT_REGISTRY) to the
    Claude Code CLI executor. Call once at startup."""
    target = registry if registry is not None else AGENT_REGISTRY
    _find_claude_cli()  # fail fast if the CLI is missing
    for agent in target.values():
        agent.executor = claude_code_executor

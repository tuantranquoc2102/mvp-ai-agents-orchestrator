"""Helpers for declaring workflow templates concisely."""
from __future__ import annotations

from typing import Any


def step(
    name: str,
    agent: str,
    *,
    tool: str | None = None,
    instruction: str = "",
    max_retries: int = 2,
    inputs_from: list[str] | None = None,
) -> dict[str, Any]:
    """Build a step template dict.

    `inputs_from` lists prior step names whose outputs should be threaded
    in as this step's inputs (resolved by the orchestrator at runtime).
    """
    return {
        "name": name,
        "agent": agent,
        "tool": tool,
        "instruction": instruction,
        "max_retries": max_retries,
        "inputs_from": inputs_from or [],
    }

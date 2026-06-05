"""Abstract LLM provider interface.

Any backend (Claude Code CLI, Anthropic API, OpenAI, local mock, ...) needs
to implement `complete(system, user, *, timeout)` and return the assistant
message as a plain string. Streaming, tool use, and multi-turn dialogue
are out of scope for this interface — the orchestrator does one one-shot
completion per workflow step.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Single-call text completion provider."""

    name: str = "unknown"

    @abstractmethod
    def complete(self, system: str, user: str, *, timeout: float = 300.0) -> str:
        """Run one completion and return the assistant's reply.

        Implementations should raise a descriptive exception on failure
        (auth, timeout, non-zero exit) so the orchestrator's retry loop can
        capture the error and either retry or surface it.
        """
        raise NotImplementedError

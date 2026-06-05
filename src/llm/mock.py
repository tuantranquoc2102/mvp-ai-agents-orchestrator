"""Deterministic mock provider — for offline runs and unit tests."""
from __future__ import annotations

from .base import LLMProvider


class MockProvider(LLMProvider):
    """Returns a short stub describing the system role and the user task.

    Output is reproducible and contains enough signal to verify wiring
    end-to-end (sections written, paths set correctly) without burning
    LLM quota.
    """

    name = "mock"

    def complete(self, system: str, user: str, *, timeout: float = 300.0) -> str:
        role_line = system.splitlines()[0].strip() if system else "(no role)"
        task_line = user.splitlines()[0].strip() if user else "(no task)"
        return (
            f"[mock] {role_line}\n"
            f"[mock] task: {task_line[:160]}"
        )

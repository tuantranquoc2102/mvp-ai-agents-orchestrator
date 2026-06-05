"""LLM providers.

A provider is anything implementing `LLMProvider.complete(system, user, *, timeout)`.
Two are shipped: `ClaudeCliProvider` (uses local Claude Code subscription via
the `claude` CLI in `--print` mode) and `MockProvider` (deterministic stub).
"""
from .base import LLMProvider
from .claude_cli import ClaudeCliProvider, ClaudeCliNotFound
from .mock import MockProvider

__all__ = [
    "LLMProvider",
    "ClaudeCliProvider",
    "ClaudeCliNotFound",
    "MockProvider",
]

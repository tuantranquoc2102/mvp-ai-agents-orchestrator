"""Claude Code subscription provider.

Shells out to the locally-installed `claude` CLI in headless print mode.
Auth comes from the user's existing Claude Code session — no
ANTHROPIC_API_KEY is read or required.
"""
from __future__ import annotations

import shutil
import subprocess

from .base import LLMProvider


class ClaudeCliNotFound(RuntimeError):
    """Raised when the `claude` executable is not on PATH."""


class ClaudeCliProvider(LLMProvider):
    """Uses `claude --print` (subscription auth) for each completion.

    Two flags are always passed:
        --system-prompt  replaces the default Claude Code system prompt so
                         CLAUDE.md / cwd / memory context don't leak into
                         per-step responses.
        --tools ""       disables Read/Grep/etc. — the model must answer
                         from the supplied user prompt, not by re-exploring
                         the filesystem.

    The user prompt is sent via stdin to avoid the variadic `--tools` flag
    accidentally consuming positional arguments.
    """

    name = "claude-code-subscription"

    def __init__(self, *, executable: str | None = None) -> None:
        exe = executable or shutil.which("claude")
        if exe is None:
            raise ClaudeCliNotFound(
                "The `claude` CLI was not found on PATH. Install Claude Code "
                "and ensure `claude --version` works in your shell."
            )
        self.executable = exe

    def complete(self, system: str, user: str, *, timeout: float = 300.0) -> str:
        result = subprocess.run(
            [self.executable, "--print",
             "--system-prompt", system,
             "--tools", ""],
            input=user,
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
        return (result.stdout or "").strip()

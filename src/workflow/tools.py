"""Tool registry + permission enforcement.

A Tool is a Python callable with metadata. Agents reference tools by
name; the runner looks them up here and validates permissions before
dispatch. Most tools in this MVP are stubs — they prove the wiring but
return placeholder data. A few (git_branch, write_rationale) do real I/O
because the feature_development workflow needs a concrete branch and a
concrete doc file in the target source repo.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.agents.base import Agent


class PermissionDenied(RuntimeError):
    """Raised when an agent tries to invoke a tool it is not allowed to use."""


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[..., Any]


# NOTE on tool kwargs: the runner currently splats `step.inputs` into each
# handler so a step can pass arbitrary kwargs. `step.inputs` is populated
# from prior step outputs via `inputs_from`, so the keys rarely match a
# stub's expected parameter names — every parameter therefore has a safe
# default and unexpected kwargs are absorbed by `**_`.

def _read_doc(path: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "read_doc", "path": path or "(no path)",
            "content": f"<contents of {path or 'unknown'}>"}


def _write_doc(path: str = "", content: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "write_doc", "path": path or "(no path)",
            "bytes_written": len(content)}


def _read_code(path: str = "", **_: Any) -> dict[str, Any]:
    """Returns a placeholder. The real codebase walker lives in `src.api.scope`
    — agents that need to look at code receive its content via the scan inputs
    rather than calling this stub."""
    return {"tool": "read_code", "path": path or "(no path)",
            "note": "stub — see src.api.scope for real codebase reading"}


def _write_code(path: str = "", content: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "write_code", "path": path or "(no path)",
            "bytes_written": len(content)}


def _run_tests(target: str = "all", **_: Any) -> dict[str, Any]:
    return {"tool": "run_tests", "target": target, "passed": 12, "failed": 0}


def _search_web(query: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "search_web", "query": query or "(no query)", "results": []}


def _create_ticket(title: str = "", body: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "create_ticket", "title": title or "(untitled)",
            "id": "TKT-001"}


# --------------------------------------------------------------------------- real I/O tools
# These three back the feature_development workflow. They do NOT come from
# task-context inputs (which is mostly prior-step LLM output) — the CLI seeds
# their kwargs into `step.inputs` directly when it builds the workflow.

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, *, max_len: int = 48) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (s[:max_len] or "task").rstrip("-")


def _git_branch(
    source_dir: str = "",
    branch_name: str = "",
    base_branch: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Create (and check out) a branch in `source_dir`.

    Idempotent: if the branch already exists, just check it out. Returns the
    branch name and the head commit so reviewers can verify what was checked
    out. Raises RuntimeError on git failure so the runner records it.
    """
    if not source_dir or not branch_name:
        raise ValueError("git_branch requires source_dir and branch_name")
    repo = Path(source_dir).resolve()
    if not (repo / ".git").exists():
        raise RuntimeError(f"{repo} is not a git repository")

    def _git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout.strip()

    existing = _git("branch", "--list", branch_name)
    if existing:
        _git("checkout", branch_name)
        action = "checked_out_existing"
    else:
        if base_branch:
            _git("checkout", "-b", branch_name, base_branch)
        else:
            _git("checkout", "-b", branch_name)
        action = "created"
    head = _git("rev-parse", "HEAD")
    return {
        "tool": "git_branch",
        "source_dir": str(repo),
        "branch": branch_name,
        "base_branch": base_branch or "(current HEAD)",
        "action": action,
        "head_commit": head,
    }


def _write_rationale(
    source_dir: str = "",
    slug: str = "",
    content: str = "",
    date: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Write `docs/changes/<date>-<slug>.md` inside `source_dir`.

    `content` is normally the rationale-step LLM summary; the CLI threads it in
    via step.inputs. We never overwrite — if the file exists, append `-N`.
    """
    if not source_dir or not slug:
        raise ValueError("write_rationale requires source_dir and slug")
    repo = Path(source_dir).resolve()
    if not repo.exists():
        raise RuntimeError(f"source_dir {repo} does not exist")
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    docs_dir = repo / "docs" / "changes"
    docs_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{date}-{_slugify(slug)}"
    candidate = docs_dir / f"{stem}.md"
    n = 2
    while candidate.exists():
        candidate = docs_dir / f"{stem}-{n}.md"
        n += 1
    body = content.strip() or (
        f"# {slug}\n\n_(no rationale content was produced — fill this in.)_\n"
    )
    candidate.write_text(body + "\n", encoding="utf-8")
    return {
        "tool": "write_rationale",
        "path": str(candidate),
        "bytes_written": len(body) + 1,
    }


def _fetch_jira(ticket_id: str = "", **_: Any) -> dict[str, Any]:
    """Stub: real Jira fetch lives in the Atlassian MCP. The CLI calls that
    directly when it can; this tool is here so the workflow can also reach
    Jira from a step if a future caller wires the MCP into the registry.
    For now returns a placeholder, NOT an error — agents downstream still
    have the original free-text description in `task_brief`."""
    return {
        "tool": "fetch_jira",
        "ticket_id": ticket_id or "(none)",
        "status": "stub — fetch via Atlassian MCP at CLI layer instead",
    }


TOOL_REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("read_doc", "Read a document.", _read_doc),
        Tool("write_doc", "Create or overwrite a document.", _write_doc),
        Tool("read_code", "Read source code (stub).", _read_code),
        Tool("write_code", "Modify or create source code.", _write_code),
        Tool("run_tests", "Execute the test suite.", _run_tests),
        Tool("search_web", "Search the web.", _search_web),
        Tool("create_ticket", "File a ticket in the tracker.", _create_ticket),
        Tool("git_branch", "Create a git branch in a source repo.", _git_branch),
        Tool("write_rationale",
             "Write docs/changes/<date>-<slug>.md in a source repo.",
             _write_rationale),
        Tool("fetch_jira", "Fetch a Jira ticket (stub).", _fetch_jira),
    ]
}


def check_permission(agent: Agent, tool_name: str) -> None:
    """Raise PermissionDenied if the agent isn't allowed to use this tool."""
    if tool_name not in TOOL_REGISTRY:
        raise KeyError(f"Unknown tool: {tool_name!r}")
    if not agent.can_use(tool_name):
        raise PermissionDenied(
            f"Agent {agent.name!r} is not allowed to use tool {tool_name!r}. "
            f"Allowed: {agent.allowed_tools}"
        )


def invoke_tool(agent: Agent, tool_name: str, **kwargs: Any) -> Any:
    check_permission(agent, tool_name)
    return TOOL_REGISTRY[tool_name].handler(**kwargs)

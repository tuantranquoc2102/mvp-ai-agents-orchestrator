"""Tool registry + permission enforcement.

A Tool is a Python callable with metadata. Agents reference tools by
name; the runner looks them up here and validates permissions before
dispatch. Most tools in this MVP are stubs — they prove the wiring but
return placeholder data.
"""
from __future__ import annotations

from dataclasses import dataclass
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

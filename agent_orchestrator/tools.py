"""Tool registry + permission enforcement.

A Tool is just a Python callable with metadata.  Agents reference tools
by name; the orchestrator looks them up here and validates permissions
before dispatch.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .agents import Agent


# Directories we never descend into when walking a codebase.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", "target", "out", ".idea", ".vscode", ".next",
    ".nuxt", ".cache", "coverage", ".tox",
}

# Map common extensions to a language label so a single dict captures
# polyglot codebases without pulling in an extra dependency.
_EXT_TO_LANG = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".fs": "F#", ".vb": "VB.NET",
    ".c": "C", ".h": "C/C++ header", ".hpp": "C++ header",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++",
    ".m": "Objective-C", ".mm": "Objective-C++",
    ".swift": "Swift", ".dart": "Dart",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    ".sql": "SQL", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".vue": "Vue", ".svelte": "Svelte",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    ".xml": "XML", ".md": "Markdown", ".rst": "reStructuredText",
    ".lua": "Lua", ".r": "R", ".jl": "Julia", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".clj": "Clojure",
    ".hs": "Haskell", ".elm": "Elm", ".nim": "Nim", ".zig": "Zig",
    ".dockerfile": "Dockerfile",
}


def _classify(p: Path) -> str:
    if p.name.lower() in ("dockerfile", "makefile", "rakefile", "gemfile"):
        return p.name.capitalize()
    return _EXT_TO_LANG.get(p.suffix.lower(), p.suffix.lower() or "<no-ext>")


def _walk_codebase(root: Path, max_listed: int = 300) -> dict[str, Any]:
    files: list[Path] = []
    for f in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in f.parts):
            continue
        if f.is_file():
            files.append(f)

    langs = Counter(_classify(f) for f in files)
    total_bytes = sum(f.stat().st_size for f in files if f.exists())
    listed = sorted(str(f.relative_to(root)) for f in files)[:max_listed]
    return {
        "kind": "directory",
        "path": str(root),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "languages": dict(langs.most_common()),
        "files": listed,
        "truncated": len(files) > max_listed,
    }


class PermissionDenied(RuntimeError):
    """Raised when an agent tries to invoke a tool it is not allowed to use."""


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[..., Any]


def _read_doc(path: str, **_: Any) -> dict[str, Any]:
    return {"tool": "read_doc", "path": path, "content": f"<contents of {path}>"}


def _write_doc(path: str, content: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "write_doc", "path": path, "bytes_written": len(content)}


def _read_code(path: str = "", max_bytes: int = 200_000, **_: Any) -> dict[str, Any]:
    """Real filesystem read.

    - If `path` is a file: returns its text content (truncated at `max_bytes`).
    - If `path` is a directory: walks it (skipping vendored dirs) and returns
      a file inventory keyed by language.
    - If `path` is empty / missing: returns an error payload instead of raising,
      so the workflow's retry loop doesn't waste attempts on a config typo.
    """
    if not path:
        return {"tool": "read_code", "error": "no path provided"}
    p = Path(path)
    if not p.exists():
        return {"tool": "read_code", "path": str(p), "error": "path not found"}
    if p.is_dir():
        return {"tool": "read_code", **_walk_codebase(p)}
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return {"tool": "read_code", "path": str(p), "error": f"read failed: {exc}"}
    return {
        "tool": "read_code",
        "kind": "file",
        "path": str(p),
        "language": _classify(p),
        "bytes": len(content),
        "truncated": len(content) > max_bytes,
        "content": content[:max_bytes],
    }


def _write_code(path: str, content: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "write_code", "path": path, "bytes_written": len(content)}


def _run_tests(target: str = "all", **_: Any) -> dict[str, Any]:
    return {"tool": "run_tests", "target": target, "passed": 12, "failed": 0}


def _search_web(query: str, **_: Any) -> dict[str, Any]:
    return {"tool": "search_web", "query": query, "results": []}


def _create_ticket(title: str, body: str = "", **_: Any) -> dict[str, Any]:
    return {"tool": "create_ticket", "title": title, "id": "TKT-001"}


TOOL_REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("read_doc", "Read a document.", _read_doc),
        Tool("write_doc", "Create or overwrite a document.", _write_doc),
        Tool("read_code", "Read source code.", _read_code),
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

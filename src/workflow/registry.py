"""Workflow template registry.

Auto-discovers every `*.py` under `templates/` that exposes a `REQUEST_TYPE`
string and a `TEMPLATE` list-of-steps. Drop a new file in `templates/` and
the orchestrator can submit it — no edits needed here.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from . import templates as _templates_pkg


def _discover() -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    for mod_info in pkgutil.iter_modules(_templates_pkg.__path__):
        # Skip private helpers like `_helpers.py`.
        if mod_info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{_templates_pkg.__name__}.{mod_info.name}")
        rt = getattr(mod, "REQUEST_TYPE", None)
        tpl = getattr(mod, "TEMPLATE", None)
        if not rt or tpl is None:
            continue
        if rt in found:
            raise ValueError(
                f"duplicate request_type {rt!r} in workflow templates"
            )
        found[rt] = tpl
    return found


WORKFLOW_REGISTRY: dict[str, list[dict[str, Any]]] = _discover()


def get_workflow_template(request_type: str) -> list[dict[str, Any]]:
    if request_type not in WORKFLOW_REGISTRY:
        raise KeyError(
            f"Unknown request_type: {request_type!r}. "
            f"Known: {sorted(WORKFLOW_REGISTRY)}"
        )
    # Shallow copy so callers can't mutate the registry.
    return [dict(s) for s in WORKFLOW_REGISTRY[request_type]]

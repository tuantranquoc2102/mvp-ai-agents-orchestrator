"""Checkpoint store.

Writes the full Workflow snapshot to disk as JSON after every step
(and on failure).  Resumption is simply: load the JSON, rebuild the
Workflow, and resume from the first non-success step.

This MVP uses local filesystem.  Swap `FileCheckpointStore` for a Redis /
S3 / DB-backed implementation later — the orchestrator only needs the
3-method protocol below.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .models import Workflow


class CheckpointStore(Protocol):
    def save(self, workflow: Workflow) -> None: ...
    def load(self, workflow_id: str) -> Workflow | None: ...
    def delete(self, workflow_id: str) -> None: ...


class FileCheckpointStore:
    def __init__(self, root: str | os.PathLike[str] = ".checkpoints") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        return self.root / f"{workflow_id}.json"

    def save(self, workflow: Workflow) -> None:
        workflow.touch()
        path = self._path(workflow.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(workflow.to_dict(), indent=2), encoding="utf-8")
        # Atomic-ish swap so a crash mid-write doesn't leave a partial file.
        os.replace(tmp, path)

    def load(self, workflow_id: str) -> Workflow | None:
        path = self._path(workflow_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Workflow.from_dict(data)

    def delete(self, workflow_id: str) -> None:
        path = self._path(workflow_id)
        if path.exists():
            path.unlink()

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))

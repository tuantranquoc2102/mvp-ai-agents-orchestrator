"""Filesystem-backed checkpoint store — one JSON file per workflow."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.workflow.models import Workflow


class FileCheckpointStore:
    """Persists each Workflow snapshot as `<root>/<workflow_id>.json`.

    The write is atomic-ish: serialize to a tmp file then `os.replace` —
    a crash mid-write leaves the previous valid file intact.
    """

    def __init__(self, root: str | os.PathLike[str] = ".checkpoints") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        return self.root / f"{workflow_id}.json"

    def save(self, workflow: "Workflow") -> None:
        workflow.touch()
        path = self._path(workflow.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(workflow.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, workflow_id: str) -> "Workflow | None":
        # Lazy import to avoid persistence <-> workflow circular at load time.
        from src.workflow.models import Workflow
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

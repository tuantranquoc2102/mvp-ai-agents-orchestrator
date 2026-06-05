"""Checkpoint store protocol."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

# `Workflow` is only used as a type hint here — guarding the import avoids a
# circular load (persistence -> workflow.models -> workflow.__init__ ->
# orchestrator -> persistence) at module-init time.
if TYPE_CHECKING:
    from src.workflow.models import Workflow


class CheckpointStore(Protocol):
    """Minimal contract for any backing store (filesystem, Redis, S3, ...).

    The orchestrator calls `save` after every step (success or failure) and
    `load` when resuming. `delete` is provided for cleanup utilities.
    """

    def save(self, workflow: "Workflow") -> None: ...
    def load(self, workflow_id: str) -> "Workflow | None": ...
    def delete(self, workflow_id: str) -> None: ...

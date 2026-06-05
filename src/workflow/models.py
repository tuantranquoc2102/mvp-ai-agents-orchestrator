"""Data models for the orchestrator.

Step     - a single unit of work assigned to an agent (+ optional tool).
Workflow - an ordered list of Steps tied to a request_type.

Both serialize to plain dicts so checkpoints can be written as JSON.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class Step:
    id: str
    name: str
    agent: str
    tool: str | None = None
    instruction: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    max_retries: int = 2
    retry_backoff_sec: float = 0.5
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        d = dict(d)
        d["status"] = StepStatus(d.get("status", StepStatus.PENDING.value))
        return cls(**d)


@dataclass
class Workflow:
    id: str
    request_type: str
    request_payload: dict[str, Any]
    steps: list[Step]
    current_step_idx: int = 0
    status: WorkflowStatus = WorkflowStatus.PENDING
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_type": self.request_type,
            "request_payload": self.request_payload,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_idx": self.current_step_idx,
            "status": self.status.value,
            "context": self.context,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Workflow":
        return cls(
            id=d["id"],
            request_type=d["request_type"],
            request_payload=d.get("request_payload", {}),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            current_step_idx=d.get("current_step_idx", 0),
            status=WorkflowStatus(d.get("status", WorkflowStatus.PENDING.value)),
            context=d.get("context", {}),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )

    def first_unfinished_idx(self) -> int:
        """Index of the earliest step that is not SUCCESS / SKIPPED."""
        for i, s in enumerate(self.steps):
            if s.status not in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                return i
        return len(self.steps)

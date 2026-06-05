"""Orchestrator — drives a Workflow through its steps and persists state.

Responsibilities:
    1. Materialize a Workflow from a request_type via the registry.
    2. Execute steps sequentially through `runner.run_step`.
    3. Persist a checkpoint after every step (success or failure).
    4. Surface a `resume()` entry point that picks up at the first
       non-success step.

Single-process, synchronous by design — the MVP cares about correctness
of the state machine, not throughput. Swap the inner loop for an
async / queue-backed runner later without changing the public API.
"""
from __future__ import annotations

from typing import Any, Callable

from src.agents.base import AGENT_REGISTRY, Agent
from src.persistence.base import CheckpointStore
from src.persistence.file_store import FileCheckpointStore

from .models import Step, StepStatus, Workflow, WorkflowStatus, new_id
from .registry import get_workflow_template
from .runner import run_step


StepHook = Callable[[Step, Workflow], None]


class Orchestrator:
    def __init__(
        self,
        checkpoint_store: CheckpointStore | None = None,
        agent_registry: dict[str, Agent] | None = None,
    ) -> None:
        self.checkpoints: CheckpointStore = checkpoint_store or FileCheckpointStore()
        self.agents: dict[str, Agent] = agent_registry or AGENT_REGISTRY

    # ------------------------------------------------------------------ submit
    def submit(
        self,
        request_type: str,
        payload: dict[str, Any] | None = None,
        *,
        on_step_start: StepHook | None = None,
        on_step_end: StepHook | None = None,
    ) -> Workflow:
        """Create a workflow from request_type and run it to completion or first failure."""
        template = get_workflow_template(request_type)
        steps = [
            Step(
                id=new_id("step"),
                name=t["name"],
                agent=t["agent"],
                tool=t.get("tool"),
                instruction=t.get("instruction", ""),
                max_retries=t.get("max_retries", 2),
                inputs={"_inputs_from": t.get("inputs_from", [])},
            )
            for t in template
        ]
        workflow = Workflow(
            id=new_id("wf"),
            request_type=request_type,
            request_payload=payload or {},
            steps=steps,
        )
        self.checkpoints.save(workflow)
        return self._execute(workflow, on_step_start, on_step_end)

    # ------------------------------------------------------------------ resume
    def resume(
        self,
        workflow_id: str,
        *,
        on_step_start: StepHook | None = None,
        on_step_end: StepHook | None = None,
    ) -> Workflow:
        """Reload a workflow from its checkpoint and continue from the first non-success step."""
        workflow = self.checkpoints.load(workflow_id)
        if workflow is None:
            raise FileNotFoundError(f"No checkpoint found for workflow_id={workflow_id!r}")
        idx = workflow.first_unfinished_idx()
        if idx < len(workflow.steps):
            failed = workflow.steps[idx]
            if failed.status == StepStatus.FAILED:
                failed.status = StepStatus.PENDING
                failed.attempts = 0
                failed.error = None
        workflow.current_step_idx = idx
        workflow.status = WorkflowStatus.RUNNING
        self.checkpoints.save(workflow)
        return self._execute(workflow, on_step_start, on_step_end)

    # ------------------------------------------------------------------ status
    def get(self, workflow_id: str) -> Workflow | None:
        return self.checkpoints.load(workflow_id)

    # ----------------------------------------------------------------- private
    def _execute(
        self,
        workflow: Workflow,
        on_step_start: StepHook | None,
        on_step_end: StepHook | None,
    ) -> Workflow:
        workflow.status = WorkflowStatus.RUNNING
        self.checkpoints.save(workflow)

        for i in range(workflow.current_step_idx, len(workflow.steps)):
            step = workflow.steps[i]
            if step.status == StepStatus.SUCCESS:
                continue

            workflow.current_step_idx = i
            self._resolve_inputs(step, workflow)

            agent = self.agents.get(step.agent)
            if agent is None:
                step.status = StepStatus.FAILED
                step.error = f"unknown agent: {step.agent!r}"
                workflow.status = WorkflowStatus.FAILED
                self.checkpoints.save(workflow)
                return workflow

            if on_step_start is not None:
                on_step_start(step, workflow)

            run_step(step, agent, workflow.context)

            if step.status == StepStatus.SUCCESS:
                workflow.context[step.name] = step.output

            self.checkpoints.save(workflow)
            if on_step_end is not None:
                on_step_end(step, workflow)

            if step.status == StepStatus.FAILED:
                workflow.status = WorkflowStatus.FAILED
                self.checkpoints.save(workflow)
                return workflow

        workflow.status = WorkflowStatus.COMPLETED
        workflow.current_step_idx = len(workflow.steps)
        self.checkpoints.save(workflow)
        return workflow

    @staticmethod
    def _resolve_inputs(step: Step, workflow: Workflow) -> None:
        """Replace the `_inputs_from` placeholder with the actual prior outputs."""
        wanted: list[str] = step.inputs.pop("_inputs_from", []) if step.inputs else []
        for dep_name in wanted:
            if dep_name in workflow.context:
                step.inputs[dep_name] = workflow.context[dep_name]

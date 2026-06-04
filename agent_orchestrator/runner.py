"""Step runner.

Owns the retry loop and the agent <-> tool dispatch for a single Step.
Pure with respect to checkpointing — the orchestrator decides when to
persist; the runner only mutates the Step in place.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from typing import Any

from .agents import Agent
from .models import Step, StepStatus
from .tools import PermissionDenied, check_permission, invoke_tool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_step(
    step: Step,
    agent: Agent,
    context: dict[str, Any],
    *,
    on_attempt: callable | None = None,  # type: ignore[valid-type]
) -> None:
    """Execute a single step with retries.  Mutates `step` in place.

    On success: step.status = SUCCESS, step.output = <payload>.
    On exhausted retries: step.status = FAILED, step.error = <last traceback>.
    """
    step.started_at = step.started_at or _now()

    # Permission check happens once up front — it's a config error, not a
    # retryable runtime error.
    if step.tool is not None:
        try:
            check_permission(agent, step.tool)
        except (PermissionDenied, KeyError) as exc:
            step.status = StepStatus.FAILED
            step.error = f"permission/lookup error: {exc}"
            step.finished_at = _now()
            return

    last_error: str | None = None
    while step.attempts <= step.max_retries:
        step.attempts += 1
        step.status = StepStatus.RUNNING
        if on_attempt is not None:
            on_attempt(step)
        try:
            agent_output = agent.execute(
                instruction=step.instruction,
                inputs=step.inputs,
                context=context,
            )
            tool_output: Any = None
            if step.tool is not None:
                # The agent's output may suggest tool kwargs; for the MVP we
                # just pass through the inputs dict so callers see *something*
                # concrete in the trace.
                tool_output = invoke_tool(agent, step.tool, **step.inputs)
            step.output = {"agent_output": agent_output, "tool_output": tool_output}
            step.status = StepStatus.SUCCESS
            step.error = None
            step.finished_at = _now()
            return
        except Exception as exc:  # noqa: BLE001 - capture-everything by design
            last_error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            step.error = last_error
            if step.attempts > step.max_retries:
                break
            time.sleep(step.retry_backoff_sec * step.attempts)  # linear backoff

    step.status = StepStatus.FAILED
    step.finished_at = _now()

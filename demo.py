"""End-to-end demo of the agent_orchestrator MVP.

Run it twice:
    python demo.py            # first run: feature_development fails mid-flow
    python demo.py resume     # second run: resume from the failed step

It exercises every feature the MVP advertises:
    * static workflow by request_type
    * retry (we inject a transient failure that succeeds on attempt 2)
    * checkpoint after every step (.checkpoints/*.json)
    * agent registry (all 14 roles)
    * tool permission (the reviewer agent is read-only)
    * step outputs saved into workflow.context
    * resume from failed step
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_orchestrator import (
    AGENT_REGISTRY,
    Orchestrator,
    StepStatus,
    TOOL_REGISTRY,
    WORKFLOW_REGISTRY,
)
from agent_orchestrator.checkpoint import FileCheckpointStore


LAST_WF_FILE = Path(".last_workflow_id")


def banner(msg: str) -> None:
    print("\n" + "=" * 72)
    print(msg)
    print("=" * 72)


def show_registry() -> None:
    banner("REGISTRY")
    print(f"Agents ({len(AGENT_REGISTRY)}):")
    for name, agent in AGENT_REGISTRY.items():
        tools = ", ".join(agent.allowed_tools) or "—"
        print(f"  - {name:<10} role={agent.role:<28} tools=[{tools}]")
    print(f"\nTools ({len(TOOL_REGISTRY)}):")
    for name, tool in TOOL_REGISTRY.items():
        print(f"  - {name:<14} {tool.description}")
    print(f"\nWorkflows ({len(WORKFLOW_REGISTRY)}):")
    for rt, steps in WORKFLOW_REGISTRY.items():
        print(f"  - {rt}: {len(steps)} steps -> {[s['name'] for s in steps]}")


def make_orchestrator_with_injected_failure() -> Orchestrator:
    """Build an orchestrator where `backend_impl` fails once, then succeeds.

    Demonstrates the retry path on a transient error.  We mutate the agent's
    executor in place; the orchestrator is decoupled from that detail.
    """
    state = {"backend_impl_failures": 0}

    def flaky_backend(agent, instruction, inputs, context):
        if state["backend_impl_failures"] < 1:
            state["backend_impl_failures"] += 1
            raise RuntimeError("simulated transient DB timeout")
        return {
            "agent": agent.name,
            "summary": f"[{agent.role}] backend implementation complete",
            "files_changed": ["api/handlers.py", "db/schema.sql"],
        }

    AGENT_REGISTRY["be_dev"].executor = flaky_backend
    return Orchestrator()


def make_orchestrator_with_hard_failure() -> Orchestrator:
    """Backend always raises — exhausts retries, workflow halts at that step."""

    def always_fails(agent, instruction, inputs, context):
        raise RuntimeError("simulated unresolved bug in backend service")

    AGENT_REGISTRY["be_dev"].executor = always_fails
    return Orchestrator()


def reset_backend_to_default() -> None:
    AGENT_REGISTRY["be_dev"].executor = None  # falls back to mock executor


def print_workflow(wf) -> None:
    print(f"\nworkflow_id : {wf.id}")
    print(f"request     : {wf.request_type}")
    print(f"status      : {wf.status.value}")
    print(f"step idx    : {wf.current_step_idx}/{len(wf.steps)}")
    for i, s in enumerate(wf.steps):
        marker = ">" if i == wf.current_step_idx and s.status != StepStatus.SUCCESS else " "
        tool = f" tool={s.tool}" if s.tool else ""
        err = f"  err={s.error.splitlines()[0]}" if s.error else ""
        print(
            f"  {marker} [{i:>2}] {s.name:<18} agent={s.agent:<10} "
            f"status={s.status.value:<8} attempts={s.attempts}{tool}{err}"
        )


def on_start(step, wf) -> None:
    print(f"  -> start  {step.name:<18} agent={step.agent} (attempt {step.attempts + 1})")


def on_end(step, wf) -> None:
    print(
        f"  <- end    {step.name:<18} status={step.status.value} "
        f"attempts={step.attempts}"
    )


def cmd_run() -> None:
    show_registry()

    # ---- Scenario A: transient failure that recovers via retry ----
    banner("RUN A — transient failure recovers on retry (feature_development)")
    orch = make_orchestrator_with_injected_failure()
    wf = orch.submit(
        "feature_development",
        payload={"feature": "checkout v2"},
        on_step_start=on_start,
        on_step_end=on_end,
    )
    print_workflow(wf)

    # ---- Scenario B: hard failure -> checkpoint -> demonstrate resume later ----
    banner("RUN B — hard failure; we'll resume in a follow-up invocation")
    orch_fail = make_orchestrator_with_hard_failure()
    wf_fail = orch_fail.submit(
        "feature_development",
        payload={"feature": "checkout v3"},
        on_step_start=on_start,
        on_step_end=on_end,
    )
    print_workflow(wf_fail)
    LAST_WF_FILE.write_text(wf_fail.id, encoding="utf-8")
    print(f"\nSaved workflow_id to {LAST_WF_FILE} — run `python demo.py resume` next.")

    # ---- Scenario C: permission denied (declarative check) ----
    banner("RUN C — permission denied for reviewer trying to write code")
    from agent_orchestrator.tools import PermissionDenied, check_permission

    reviewer = AGENT_REGISTRY["reviewer"]
    try:
        check_permission(reviewer, "write_code")
    except PermissionDenied as exc:
        print(f"OK: blocked as expected -> {exc}")


def cmd_resume() -> None:
    if not LAST_WF_FILE.exists():
        print("No prior workflow_id found.  Run `python demo.py` first.")
        sys.exit(1)
    wf_id = LAST_WF_FILE.read_text(encoding="utf-8").strip()
    banner(f"RESUME — workflow_id={wf_id}")

    # First, show the persisted state on disk.
    store = FileCheckpointStore()
    wf_before = store.load(wf_id)
    if wf_before is None:
        print(f"Checkpoint missing for {wf_id!r}")
        sys.exit(1)
    print("Before resume:")
    print_workflow(wf_before)

    # Patch the backend agent so it succeeds this time.
    reset_backend_to_default()

    orch = Orchestrator()
    wf_after = orch.resume(wf_id, on_step_start=on_start, on_step_end=on_end)
    print("\nAfter resume:")
    print_workflow(wf_after)

    # Dump the persisted JSON so the user can inspect the checkpoint.
    cp_path = Path(".checkpoints") / f"{wf_id}.json"
    if cp_path.exists():
        banner(f"CHECKPOINT FILE — {cp_path}")
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        # Strip noisy fields for readability.
        for s in data["steps"]:
            if s.get("error") and len(s["error"]) > 120:
                s["error"] = s["error"].splitlines()[0] + "  ..."
        print(json.dumps(data, indent=2)[:2000] + "\n... (truncated)")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        cmd_run()
    elif cmd == "resume":
        cmd_resume()
    else:
        print(f"Unknown command: {cmd}.  Use `run` or `resume`.")
        sys.exit(2)


if __name__ == "__main__":
    main()

"""One-off: re-run just the `rationale` step of a completed workflow.

Loads the checkpoint, flips the rationale step back to PENDING, then calls
Orchestrator.resume() — the executor skips already-SUCCESS steps, so only
the reset step runs. Finally re-applies post_finalize_rationale so the
file on disk reflects the new LLM output.
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from src.agents import use_llm_for_all_agents
from src.api.feature_cli import on_start, on_end, post_finalize_rationale
from src.llm import ClaudeCliProvider
from src.persistence.file_store import FileCheckpointStore
from src.workflow import Orchestrator
from src.workflow.models import StepStatus

WF_ID = "wf_6a2c08800465"
RUN_DIR = Path("output") / WF_ID

provider = ClaudeCliProvider()
use_llm_for_all_agents(provider)

store = FileCheckpointStore(root=RUN_DIR / "checkpoint")
wf = store.load(WF_ID)
assert wf is not None, f"no checkpoint at {RUN_DIR / 'checkpoint'}"

# Flip rationale back to PENDING; clear its prior output so post_finalize
# rewrites from the new summary, not the old one.
target_step = next(s for s in wf.steps if s.name == "rationale")
target_step.status = StepStatus.PENDING
target_step.attempts = 0
target_step.output = None
target_step.error = None
target_step.started_at = None
target_step.finished_at = None

# Also reload the template's instruction so the prompt change is picked up
# (checkpoint stored the OLD instruction at submit time).
from src.workflow.templates.feature_development import TEMPLATE
rationale_tpl = next(t for t in TEMPLATE if t["name"] == "rationale")
target_step.instruction = rationale_tpl["instruction"]

store.save(wf)

orch = Orchestrator(checkpoint_store=store)
wf = orch.resume(WF_ID, on_step_start=on_start, on_step_end=on_end)

post_finalize_rationale(wf)

print(f"\nstatus: {wf.status.value}")
rationale = next(s for s in wf.steps if s.name == "rationale")
print(f"rationale step: {rationale.status.value}, attempts={rationale.attempts}")
if rationale.output:
    tool_out = (rationale.output or {}).get("tool_output") or {}
    print(f"doc path: {tool_out.get('path')}")

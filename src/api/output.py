"""Write a completed workflow as a human-browsable markdown tree.

Layout under `run_dir/` (typically `output/<wf_id>/`):
    README.md                       index + metadata + links
    scan.json                       raw scope output
    01_inventory/inventory.md       step #1
    02_architecture/architecture.md step #2
    ...
    05_diagram/diagram.md           if diagram step present
    05_diagram/diagram.mmd          extracted + sanitized mermaid
    checkpoint/<wf_id>.json         orchestrator state (for resume)

The checkpoint file lives under run_dir because we point FileCheckpointStore
at `run_dir / 'checkpoint'` — everything produced by the run is under one
directory.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents import AGENT_REGISTRY
from src.workflow.models import Step, Workflow

from .mermaid import extract_mermaid, sanitize_mermaid


def _step_summary(step: Step) -> str:
    """Pull the assistant text out of a step's structured output."""
    if not step.output or not isinstance(step.output, dict):
        return ""
    agent_out = step.output.get("agent_output")
    if isinstance(agent_out, dict):
        return str(agent_out.get("summary") or "")
    return str(agent_out or "")


def _render_readme(
    wf: Workflow,
    scan: dict[str, Any],
    target_path: Path,
    sections: list[tuple[int, str, Path]],
) -> str:
    lang_summary = ", ".join(
        f"{name} ({count})" for name, count in list(scan["languages"].items())[:8]
    )
    lines = [
        f"# Codebase Analysis — `{target_path.name}`",
        "",
        f"- **Target:** `{target_path}`",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- **Workflow ID:** `{wf.id}` (status: `{wf.status.value}`)",
        f"- **Files scanned:** {scan['file_count']:,} "
        f"({scan['total_bytes']:,} bytes)",
        f"- **Languages:** {lang_summary or '—'}",
        "",
        "## Sections",
        "",
    ]
    for idx, name, rel in sections:
        lines.append(f"{idx}. [{name.replace('_', ' ').title()}]"
                     f"({rel.as_posix()})")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append("- Raw scan data: [`scan.json`](scan.json)")
    lines.append(f"- Orchestrator checkpoint: "
                 f"[`checkpoint/{wf.id}.json`](checkpoint/{wf.id}.json) — "
                 "pass `--run-name <wf_id>` to a future invocation to resume.")
    return "\n".join(lines) + "\n"


def write_outputs(
    wf: Workflow,
    scan: dict[str, Any],
    run_dir: Path,
    target_path: Path,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "scan.json").write_text(
        json.dumps(scan, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    sections: list[tuple[int, str, Path]] = []
    for i, step in enumerate(wf.steps, start=1):
        section_dir = run_dir / f"{i:02d}_{step.name}"
        section_dir.mkdir(exist_ok=True)

        summary = _step_summary(step)
        agent_role = (
            AGENT_REGISTRY[step.agent].role if step.agent in AGENT_REGISTRY else step.agent
        )

        body = (
            f"# {step.name.replace('_', ' ').title()}\n\n"
            f"_Agent: `{step.agent}` ({agent_role})_  \n"
            f"_Status: `{step.status.value}` · attempts: {step.attempts}_\n\n"
            f"---\n\n"
            f"{summary if summary else '_(no content — step did not produce output)_'}\n"
        )
        md_path = section_dir / f"{step.name}.md"
        md_path.write_text(body, encoding="utf-8")
        sections.append((i, step.name, md_path.relative_to(run_dir)))

        if step.name == "diagram":
            mmd = extract_mermaid(summary)
            if mmd:
                mmd_safe = sanitize_mermaid(mmd)
                (section_dir / "diagram.mmd").write_text(
                    mmd_safe + "\n", encoding="utf-8",
                )

    (run_dir / "README.md").write_text(
        _render_readme(wf, scan, target_path, sections),
        encoding="utf-8",
    )
    return run_dir

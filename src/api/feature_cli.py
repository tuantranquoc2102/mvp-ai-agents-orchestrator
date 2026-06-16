"""Command-line entry point for the feature_development workflow.

Usage:
    python -m src.api.feature_cli --source-dir <repo> --task-type fullstack \\
        --description "Add CSV export to the reports page"

The CLI handles the parts the workflow template can't:
  * gathering the task brief (free text, file, stdin, or Jira ID metadata),
  * pre-scanning the SOURCE repo so the `scope` step has real file paths,
  * choosing which steps to keep (BE-only / FE-only / migration audit),
  * creating the real git branch and writing the rationale doc into the
    SOURCE repo via the `git_branch` / `write_rationale` tools.

Direct-input ergonomics (no Jira required):
  --description "..."           one-liner
  --description-file brief.md   long structured input (markdown)
  cat brief.md | python -m ...  stdin (no flag needed)
  --init-brief brief.md         write a fillable template to disk and exit

Jira ID is accepted (--jira-id), but fetching the ticket body lives outside
this CLI — pair it with --description / --description-file when running
unattended. The ticket ID is preserved in the rationale doc for traceability.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force utf-8 stdout/stderr so LLM responses don't crash on Windows cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from src.agents import use_llm_for_all_agents
from src.llm import ClaudeCliNotFound, ClaudeCliProvider, MockProvider
from src.persistence.file_store import FileCheckpointStore
from src.workflow import Orchestrator
from src.workflow.models import Step, Workflow, WorkflowStatus, new_id
from src.workflow.templates.feature_development import (
    TASK_TYPE_STEPS,
    applicable_steps,
)
from src.workflow.tools import _slugify

from .output import write_outputs
from .scope import walk_codebase


# --------------------------------------------------------------------------- formatting

def banner(msg: str) -> None:
    print("\n" + "=" * 72)
    print(msg)
    print("=" * 72)


def on_start(step, wf) -> None:
    print(f"  -> start  {step.name:<18} agent={step.agent:<10} "
          f"(attempt {step.attempts + 1})")


def on_end(step, wf) -> None:
    print(f"  <- end    {step.name:<18} status={step.status.value:<8} "
          f"attempts={step.attempts}")


# --------------------------------------------------------------------------- brief

BRIEF_TEMPLATE = """\
# Feature brief

> Fill in the fields below, then pass this file via --description-file.

## Title
<one-line summary, e.g. "Add CSV export to the reports page">

## Why
<business + technical motivation. Why now? Who asked? What does it unlock?>

## Scope
<bulleted list of what's in scope>

## Out of scope
<things that look related but are explicitly NOT changing>

## Acceptance criteria
<bulleted, testable, e.g. "User clicks Export → CSV downloads with all
current filters applied; columns match the table">

## Notes / Links
<Jira ID, Figma, Confluence, prior PRs, anything else>
"""


def _read_stdin_if_piped() -> str | None:
    if sys.stdin.isatty():
        return None
    data = sys.stdin.read().strip()
    return data or None


def collect_description(args: argparse.Namespace) -> str:
    """Resolve the task description from --description / file / stdin.

    Order: --description-file beats --description beats stdin. If multiple
    are provided we concatenate (file first, then explicit text). The CLI
    refuses to run with an empty description because every downstream step
    keys off it.
    """
    parts: list[str] = []
    if args.description_file:
        path = Path(args.description_file).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"--description-file not found: {path}")
        parts.append(path.read_text(encoding="utf-8").strip())
    if args.description:
        parts.append(args.description.strip())
    if not parts:
        piped = _read_stdin_if_piped()
        if piped:
            parts.append(piped)
    text = "\n\n".join(p for p in parts if p)
    if not text:
        raise ValueError(
            "no description supplied. Provide one of:\n"
            "  --description \"...\"\n"
            "  --description-file brief.md\n"
            "  cat brief.md | python -m src.api.feature_cli ...\n"
            "  --init-brief brief.md   (then edit and pass --description-file)"
        )
    return text


def _path_or_label(value: str | None) -> tuple[str | None, Path | None]:
    """If `value` resolves to an existing directory, return (label, path);
    otherwise treat it as a plain service-name label. Lets the user pass
    --migrate-from as either 'node-auth' or a full repo path."""
    if not value:
        return None, None
    candidate = Path(value).expanduser()
    if candidate.exists() and candidate.is_dir():
        resolved = candidate.resolve()
        return resolved.name, resolved
    return value, None


def build_task_brief(args: argparse.Namespace, description: str) -> dict:
    """Bundle the free-text description with structured metadata.

    Returned dict lands in `workflow.context['task_brief']` and is read by
    the `intake` step (and threaded through to later steps via inputs_from).
    """
    from_label, from_path = _path_or_label(args.migrate_from)
    to_label, _to_path = _path_or_label(args.migrate_to)
    return {
        "description": description,
        "jira_id": args.jira_id,
        "source_dir": str(Path(args.source_dir).resolve()),
        "task_type": args.task_type,
        "migrate_from": from_label,
        "migrate_to": to_label,
        "migrate_from_path": str(from_path) if from_path else None,
        "branch_name": args.branch or _default_branch(args, description),
        "slug": _slugify(args.branch or _first_line(description)),
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _first_line(text: str) -> str:
    """Pick a meaningful slug source from a brief.

    Prefer the value under a `## Title` (or `# Title`) heading; fall back
    to the first non-header line. The naive 'first non-empty line' picked
    up generic h1s like '# Feature brief' which made every branch slug
    look the same.
    """
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        if raw.strip().lower().lstrip("#").strip() == "title":
            for follow in lines[i + 1:]:
                v = follow.strip().lstrip("#").strip()
                if v and not v.startswith("<") and not v.lower().startswith("title"):
                    return v
            break
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#"):
            return s
    return "task"


def _default_branch(args: argparse.Namespace, description: str) -> str:
    base = _slugify(_first_line(description))
    if args.task_type == "migration" or (args.migrate_from and args.migrate_to):
        return f"migration/{base}"
    return f"feature/{base}"


# --------------------------------------------------------------------------- workflow build

def build_workflow(
    brief: dict,
    source_scan: dict,
    rationale_date: str,
    migrate_from_scan: dict | None = None,
) -> Workflow:
    """Materialize a feature_development workflow filtered for this run.

    Steps that touch the real source repo (`branch`, `rationale`) get their
    tool kwargs seeded directly into step.inputs — those values come from
    the brief, not from prior-step LLM output, so inputs_from isn't enough.
    """
    is_migration = bool(brief["migrate_from"] and brief["migrate_to"]) or brief["task_type"] == "migration"
    template = applicable_steps(brief["task_type"], is_migration=is_migration)

    steps: list[Step] = []
    for t in template:
        inputs: dict = {"_inputs_from": t.get("inputs_from", [])}
        if t["name"] == "branch":
            inputs.update({
                "source_dir": brief["source_dir"],
                "branch_name": brief["branch_name"],
            })
        elif t["name"] == "rationale":
            inputs.update({
                "source_dir": brief["source_dir"],
                "slug": brief["slug"],
                "date": rationale_date,
                "content": "",  # filled at runtime from prior step output
            })
        steps.append(Step(
            id=new_id("step"),
            name=t["name"],
            agent=t["agent"],
            tool=t.get("tool"),
            instruction=t.get("instruction", ""),
            max_retries=t.get("max_retries", 2),
            inputs=inputs,
        ))

    wf = Workflow(
        id=new_id("wf"),
        request_type="feature_development",
        request_payload={
            "task_type": brief["task_type"],
            "source_dir": brief["source_dir"],
            "branch_name": brief["branch_name"],
            "jira_id": brief["jira_id"],
            "is_migration": is_migration,
        },
        steps=steps,
    )
    wf.context["task_brief"] = brief
    wf.context["source_scan"] = source_scan
    if migrate_from_scan is not None:
        wf.context["migrate_from_scan"] = migrate_from_scan
    return wf


def thread_rationale_content(step, wf) -> None:
    """Just before the rationale tool runs, copy the LLM output of the
    rationale step into its `content` input so write_rationale has real
    text to drop in the source repo. Hook: on_step_start."""
    if step.name != "rationale":
        return
    # The rationale step's LLM call has already produced agent_output by the
    # time the tool runs — but agent.execute and invoke_tool live in the
    # same run_step() call, so at on_step_start the LLM hasn't run yet.
    # We can't capture it here; instead, write_rationale gets a placeholder
    # and we rewrite the file after the workflow finishes (see post_finalize).
    return


def post_finalize_rationale(wf: Workflow) -> None:
    """After the workflow finishes, rewrite the rationale doc with the actual
    LLM-produced text. The tool wrote a placeholder when invoked because the
    agent_output isn't available to the tool kwargs at runtime — patching
    after the fact keeps the workflow steps simple."""
    rationale_step = next((s for s in wf.steps if s.name == "rationale"), None)
    if not rationale_step or not rationale_step.output:
        return
    tool_out = rationale_step.output.get("tool_output") or {}
    path_str = tool_out.get("path")
    agent_out = rationale_step.output.get("agent_output") or {}
    summary = agent_out.get("summary") if isinstance(agent_out, dict) else None
    if not path_str or not summary:
        return
    path = Path(path_str)
    if not path.exists():
        return
    path.write_text(str(summary).strip() + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- CLI

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Run the feature_development workflow against a real source repo. "
            "Produces: a feature branch in the repo, a rationale doc under "
            "docs/changes/, and an LLM-produced implementation plan under "
            "the output directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "EXAMPLES\n"
            "  # one-liner description, BE only\n"
            "  python -m src.api.feature_cli --source-dir ../api \\\n"
            "      --task-type backend \\\n"
            "      --description \"Add /v1/reports/export endpoint returning CSV\"\n\n"
            "  # long brief from a file, fullstack feature\n"
            "  python -m src.api.feature_cli --source-dir ../app \\\n"
            "      --task-type fullstack --description-file brief.md\n\n"
            "  # migration: node service -> go service\n"
            "  python -m src.api.feature_cli --source-dir ../auth-go \\\n"
            "      --task-type migration --migrate-from node-auth \\\n"
            "      --migrate-to go-auth --description-file brief.md\n\n"
            "  # write a fillable brief template, then edit\n"
            "  python -m src.api.feature_cli --init-brief brief.md\n"
        ),
    )
    ap.add_argument("--source-dir", type=Path,
                    help="Path to the source repository to modify "
                         "(must be a git repo). Required unless --init-brief.")
    ap.add_argument("--task-type", choices=sorted(TASK_TYPE_STEPS),
                    help=f"Which steps to include. "
                         f"Choices: {sorted(TASK_TYPE_STEPS)}.")
    ap.add_argument("--description", default=None,
                    help="Task description (free text).")
    ap.add_argument("--description-file", type=Path, default=None,
                    help="Path to a markdown brief. Concatenated before "
                         "--description if both are given.")
    ap.add_argument("--jira-id", default=None,
                    help="Optional Jira ticket id, e.g. PROJ-123. Stored "
                         "as metadata in the rationale doc; the ticket "
                         "body is NOT fetched by this CLI — supply the "
                         "description separately.")
    ap.add_argument("--migrate-from", default=None,
                    help="Source system name for migration tasks "
                         "(e.g. 'node-auth-service'). Triggers the "
                         "migration_audit step.")
    ap.add_argument("--migrate-to", default=None,
                    help="Target system name for migration tasks.")
    ap.add_argument("--branch", default=None,
                    help="Override the auto-generated branch name "
                         "(default: feature/<slug> or migration/<slug>).")
    ap.add_argument("--init-brief", type=Path, default=None,
                    help="Write a fillable brief template to this path "
                         "and exit. Does not run the workflow.")
    ap.add_argument("--mock", action="store_true",
                    help="Use the mock LLM provider (offline, deterministic).")
    ap.add_argument("--output-dir", default="output", type=Path,
                    help="Root directory for outputs (default: ./output).")
    ap.add_argument("--run-name", default=None,
                    help="Subdirectory name under --output-dir "
                         "(default: the workflow ID).")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    if args.init_brief:
        path = args.init_brief.expanduser().resolve()
        if path.exists():
            print(f"error: {path} already exists; refusing to overwrite",
                  file=sys.stderr)
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BRIEF_TEMPLATE, encoding="utf-8")
        print(f"wrote brief template to {path}")
        print("Edit it, then re-run with --description-file "
              f"{path.name} and --source-dir / --task-type.")
        return 0

    if args.source_dir is None or args.task_type is None:
        print("error: --source-dir and --task-type are required "
              "(unless --init-brief).", file=sys.stderr)
        return 2

    source_dir = args.source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        print(f"error: --source-dir {source_dir} is not a directory",
              file=sys.stderr)
        return 2
    if not (source_dir / ".git").exists():
        print(f"error: --source-dir {source_dir} is not a git repo "
              "(no .git directory). Initialize git there first.",
              file=sys.stderr)
        return 2

    if bool(args.migrate_from) ^ bool(args.migrate_to):
        print("error: --migrate-from and --migrate-to must be set together "
              "(or neither).", file=sys.stderr)
        return 2

    try:
        description = collect_description(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # ---- LLM provider ----
    if args.mock:
        provider = MockProvider()
        use_llm_for_all_agents(provider)
        print("LLM         : mock (deterministic stub)")
    else:
        try:
            provider = ClaudeCliProvider()
            use_llm_for_all_agents(provider)
            print("LLM         : claude CLI (subscription)")
        except ClaudeCliNotFound as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            print("Falling back to mock provider.", file=sys.stderr)
            provider = MockProvider()
            use_llm_for_all_agents(provider)

    # ---- scope the source repo ----
    banner(f"SCANNING source repo {source_dir}")
    source_scan = walk_codebase(source_dir)
    top_langs = list(source_scan["languages"].items())[:8]
    print(f"files       : {source_scan['file_count']}")
    print(f"total bytes : {source_scan['total_bytes']:,}")
    print(f"languages   : {top_langs}")

    # ---- build & run ----
    brief = build_task_brief(args, description)
    rationale_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    migrate_from_scan: dict | None = None
    if brief.get("migrate_from_path"):
        from_path = Path(brief["migrate_from_path"])
        banner(f"SCANNING migrate-from repo {from_path}")
        migrate_from_scan = walk_codebase(from_path)
        top_langs_from = list(migrate_from_scan["languages"].items())[:8]
        print(f"files       : {migrate_from_scan['file_count']}")
        print(f"total bytes : {migrate_from_scan['total_bytes']:,}")
        print(f"languages   : {top_langs_from}")

    wf = build_workflow(brief, source_scan, rationale_date, migrate_from_scan)

    run_name = args.run_name or wf.id
    run_dir = (args.output_dir / run_name).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    is_migration = bool(args.migrate_from) or args.task_type == "migration"
    print(f"task type   : {args.task_type}"
          f"{' (migration audit on)' if is_migration else ''}")
    print(f"branch      : {brief['branch_name']}")
    print(f"workflow id : {wf.id}")
    print(f"run dir     : {run_dir}")
    if args.jira_id:
        print(f"jira ticket : {args.jira_id}")
    if args.migrate_from:
        print(f"migration   : {args.migrate_from} -> {args.migrate_to}")

    store = FileCheckpointStore(root=run_dir / "checkpoint")
    orch = Orchestrator(checkpoint_store=store)
    orch.checkpoints.save(wf)

    banner("RUNNING WORKFLOW feature_development")
    wf = orch._execute(wf, on_step_start=on_start, on_step_end=on_end)

    # Rationale doc was written with a placeholder by the tool — rewrite it
    # now with the actual LLM-produced text.
    post_finalize_rationale(wf)

    banner(f"RESULT — status={wf.status.value}")
    for i, s in enumerate(wf.steps):
        marker = "OK" if s.status.value == "success" else s.status.value.upper()
        err = f"  err={s.error.splitlines()[0]}" if s.error else ""
        print(f"  [{i}] {s.name:<18} {marker:<10} attempts={s.attempts}{err}")

    write_outputs(wf, source_scan, run_dir, source_dir)
    banner(f"OUTPUT WRITTEN -> {run_dir}")
    for p in sorted(run_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(run_dir).as_posix()
            print(f"  {rel}  ({p.stat().st_size:,} bytes)")

    # Surface the in-repo artifacts so the user knows where to look.
    print()
    print("In-repo artifacts:")
    print(f"  branch: {brief['branch_name']} (in {source_dir})")
    rationale_step = next((s for s in wf.steps if s.name == "rationale"), None)
    if rationale_step and rationale_step.output:
        tool_out = (rationale_step.output or {}).get("tool_output") or {}
        if tool_out.get("path"):
            print(f"  doc:    {tool_out['path']}")

    if wf.status != WorkflowStatus.COMPLETED:
        print(
            f"\nWorkflow did not complete. Resume with:\n"
            f"  FileCheckpointStore(root=r'{run_dir / 'checkpoint'}')\n"
            f"  Orchestrator(checkpoint_store=store).resume({wf.id!r})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

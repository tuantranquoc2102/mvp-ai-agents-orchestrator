"""Command-line entry point for the codebase analyzer.

Usage (after refactor, both paths work):
    python -m src.api.cli <path> [flags]
    python analyze_codebase.py <path> [flags]      # shim at repo root

The shim exists so the original command lines from earlier work still run
unchanged.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Force utf-8 stdout/stderr so LLM responses (arrows, em-dashes, etc.) don't
# crash on Windows cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from src.agents import AGENT_REGISTRY, use_llm_for_all_agents
from src.config import DIAGRAM_INSTRUCTION, FEATURE_DEFAULTS
from src.llm import ClaudeCliNotFound, ClaudeCliProvider, MockProvider
from src.persistence.file_store import FileCheckpointStore
from src.workflow import Orchestrator
from src.workflow.models import Step, Workflow, WorkflowStatus, new_id
from src.workflow.registry import get_workflow_template

from .output import write_outputs
from .scope import expand_feature_scope, scope_by_feature, walk_codebase
from .trace import llm_trace_discovery


# --------------------------------------------------------------------------- formatting

def banner(msg: str) -> None:
    print("\n" + "=" * 72)
    print(msg)
    print("=" * 72)


def on_start(step, wf) -> None:
    print(f"  -> start  {step.name:<14} agent={step.agent:<10} "
          f"(attempt {step.attempts + 1})")


def on_end(step, wf) -> None:
    print(f"  <- end    {step.name:<14} status={step.status.value:<8} "
          f"attempts={step.attempts}")


# --------------------------------------------------------------------------- workflow build

def build_workflow(scan: dict, with_diagram: bool) -> Workflow:
    """Materialize an `analyze_codebase` workflow + pre-seed scan context.

    When `with_diagram`, appends a `diagram` step asking the architect for a
    Mermaid flowchart. When the scan is feature-scoped, every step's
    instruction gets a SCOPE prefix so the LLM stays narrowly focused.
    """
    template = get_workflow_template("analyze_codebase")
    if with_diagram:
        template.append({
            "name": "diagram",
            "agent": "architect",
            "tool": None,
            "instruction": DIAGRAM_INSTRUCTION,
            "max_retries": 2,
            "inputs_from": ["codebase_scan", "architecture", "report"],
        })

    if scan.get("kind") == "feature_scope":
        feature = scan.get("feature_query", "(unspecified)")
        scope_prefix = (
            f"SCOPE — focus exclusively on the feature `{feature}`. "
            "The `codebase_scan` input is already pre-filtered to files "
            "that reference this feature; do NOT describe the broader "
            "codebase. If the inputs contain file content, read it before "
            "drawing conclusions.\n\n"
        )
        for t in template:
            t["instruction"] = scope_prefix + (t.get("instruction") or "")

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
    wf = Workflow(
        id=new_id("wf"),
        request_type="analyze_codebase",
        request_payload={
            "path": scan["path"],
            "with_diagram": with_diagram,
            "feature_query": scan.get("feature_query"),
        },
        steps=steps,
    )
    wf.context["codebase_scan"] = scan
    return wf


# --------------------------------------------------------------------------- CLI

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Agent-orchestrated codebase analyzer. Default mode: walk an "
            "entire codebase and produce inventory/architecture/quality/"
            "report markdown. --feature mode: scope to one endpoint / "
            "function / config key and (with --expand) follow symbol "
            "references to handlers/services/repos."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("path", help="Path to the codebase directory to analyze.")
    ap.add_argument("--mock", action="store_true",
                    help="Use the mock LLM provider (offline, deterministic).")
    ap.add_argument("--mermaid", action="store_true",
                    help="Add a Mermaid business-flow diagram step.")
    ap.add_argument("--output-dir", default="output", type=Path,
                    help="Root directory for outputs (default: ./output).")
    ap.add_argument("--run-name", default=None,
                    help="Subdirectory name under --output-dir "
                         "(default: the workflow ID, e.g. wf_a9490452ebb4).")
    ap.add_argument("--feature", default=None,
                    help="Restrict analysis to files referencing this string "
                         "(e.g. '/v4/chartmonthly'). The codebase is NOT "
                         "walked in full — only matched files (and their "
                         "content) are sent to the LLM.")
    ap.add_argument("--feature-max-files", type=int, default=None,
                    help="Cap on matched files when --feature is set "
                         f"(default: {FEATURE_DEFAULTS['max_files']}).")
    ap.add_argument("--exclude-dir", action="append", default=[],
                    metavar="NAME",
                    help="Additional directory name to skip during feature "
                         "search (repeatable). Built-in skips include "
                         ".git, node_modules, output, .checkpoints, etc.")
    ap.add_argument("--include-non-source", action="store_true",
                    help="Also grep non-source files (.json/.yaml/.md/.toml/"
                         "...). By default --feature only scans source code "
                         "extensions.")
    ap.add_argument("--expand", type=int, default=0, metavar="HOPS",
                    help="After the initial feature grep, run HOPS extra "
                         "passes that extract qualified / UpperCamel symbols "
                         "from matched files and grep the tree for them. "
                         "1 typically reaches handlers + middleware; 2 also "
                         "pulls in services / repos. Max 2. Default: 0. "
                         "Prefer --trace for endpoint analysis.")
    ap.add_argument("--trace", action="store_true",
                    help="LLM-guided call-chain discovery (recommended for "
                         "endpoint analysis). Makes 1-2 extra LLM calls to "
                         "identify exactly which classes/methods are invoked "
                         "from the entry-point file, then greps for those "
                         "names only. Much more focused than --expand, but "
                         "requires a real provider (silently skips under "
                         "--mock). Mutually exclusive with --expand.")
    ap.add_argument("--trace-rounds", type=int, default=2,
                    help="Trace mode rounds (default: 2). Round 1 finds "
                         "services from the controller; round 2 finds repos "
                         "/ external clients from those services.")
    ap.add_argument("--trace-max-files", type=int, default=20,
                    help="Trace mode file cap (default: 20). Smaller than "
                         "--expand because trace only follows call-chain.")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    target = Path(args.path).resolve()
    if not target.exists() or not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return 2
    if args.trace and args.expand > 0:
        print("error: --trace and --expand are mutually exclusive. "
              "Pick one: --trace for LLM-guided call-chain discovery "
              "(focused), --expand for blind symbol grep (broad).",
              file=sys.stderr)
        return 2

    # ---- LLM provider (set up first so --trace can use it) ----
    if args.mock:
        provider = MockProvider()
        use_llm_for_all_agents(provider)
        print(f"LLM         : mock (deterministic stub)")
    else:
        try:
            provider = ClaudeCliProvider()
            use_llm_for_all_agents(provider)
            print(f"LLM         : claude CLI (subscription)")
        except ClaudeCliNotFound as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            print("Falling back to mock provider.", file=sys.stderr)
            provider = MockProvider()
            use_llm_for_all_agents(provider)

    # ---- scope ----
    if args.feature:
        banner(f"SCOPING by feature  '{args.feature}'  under  {target}")
        effective_max = args.feature_max_files
        if effective_max is None and args.expand > 0:
            effective_max = FEATURE_DEFAULTS["max_files"] + 20 * args.expand
            print(f"auto cap     : --feature-max-files={effective_max} "
                  f"(scaled by --expand {args.expand})")
        scan = scope_by_feature(
            target, args.feature,
            max_files=effective_max,
            extra_skip_dirs=set(args.exclude_dir),
            include_non_source=args.include_non_source,
        )
        if scan["file_count"] == 0:
            print(f"error: no source files under {target} contain "
                  f"{args.feature!r}. Try --include-non-source if the "
                  "endpoint is declared only in config/YAML/JSON.",
                  file=sys.stderr)
            return 2

        if args.trace:
            print(f"hop 0 matches: {scan['file_count']}")
            print(f"trace mode   : LLM-guided, "
                  f"{args.trace_rounds} round(s), cap {args.trace_max_files}")
            scan = llm_trace_discovery(
                scan, target, provider,
                max_rounds=args.trace_rounds,
                max_files=args.trace_max_files,
                extra_skip_dirs=set(args.exclude_dir),
                include_non_source=args.include_non_source,
            )
            for entry in scan.get("expansion", {}).get("per_hop", []):
                stopped = f" (stopped: {entry['stopped']})" if entry.get("stopped") else ""
                print(f"round {entry['hop']} +{entry['new_files']} files "
                      f"via {len(entry['identifiers'])} identifiers{stopped}")
        elif args.expand > 0:
            print(f"hop 0 matches: {scan['file_count']}")
            scan = expand_feature_scope(
                scan, target, hops=args.expand,
                extra_skip_dirs=set(args.exclude_dir),
                include_non_source=args.include_non_source,
            )
            for entry in scan.get("expansion", {}).get("per_hop", []):
                stopped = f" (stopped: {entry['stopped']})" if entry.get("stopped") else ""
                print(f"hop {entry['hop']} +{entry['new_files']} files "
                      f"via {len(entry['symbols'])} symbols{stopped}")

        print(f"matched files: {scan['file_count']}"
              f"{' (truncated)' if scan['truncated'] else ''}")
        print(f"total bytes  : {scan['total_bytes']:,}")
        print(f"languages    : {list(scan['languages'].items())[:8]}")
        if args.exclude_dir:
            print(f"extra skips  : {args.exclude_dir}")
        if args.include_non_source:
            print("non-source   : enabled (.json/.yaml/.md/... included)")
        print("top matches  :")
        for m in scan["matched_files"][:10]:
            hop_tag = f" hop={m['hop']}" if m.get("hop") else ""
            print(f"  {m['match_count']:>3}x  {m['path']}  ({m['language']}, "
                  f"{m['size_bytes']:,}B, {m['content_mode']}{hop_tag})")
    else:
        banner(f"SCANNING {target}")
        scan = walk_codebase(target)
        top_langs = list(scan["languages"].items())[:8]
        print(f"files       : {scan['file_count']}")
        print(f"total bytes : {scan['total_bytes']:,}")
        print(f"languages   : {top_langs}")
        if scan["truncated"]:
            print(f"(file list truncated — showing first {len(scan['files'])})")

    # ---- run ----
    wf = build_workflow(scan, with_diagram=args.mermaid)
    run_name = args.run_name or wf.id
    run_dir = (args.output_dir / run_name).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"with diagram: {args.mermaid}")
    print(f"workflow id : {wf.id}")
    print(f"run dir     : {run_dir}")

    store = FileCheckpointStore(root=run_dir / "checkpoint")
    orch = Orchestrator(checkpoint_store=store)
    orch.checkpoints.save(wf)

    banner("RUNNING WORKFLOW analyze_codebase")
    wf = orch._execute(wf, on_step_start=on_start, on_step_end=on_end)

    banner(f"RESULT — status={wf.status.value}")
    for i, s in enumerate(wf.steps):
        marker = "OK" if s.status.value == "success" else s.status.value.upper()
        err = f"  err={s.error.splitlines()[0]}" if s.error else ""
        print(f"  [{i}] {s.name:<14} {marker:<10} attempts={s.attempts}{err}")

    write_outputs(wf, scan, run_dir, target)
    banner(f"OUTPUT WRITTEN -> {run_dir}")
    for p in sorted(run_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(run_dir).as_posix()
            print(f"  {rel}  ({p.stat().st_size:,} bytes)")

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

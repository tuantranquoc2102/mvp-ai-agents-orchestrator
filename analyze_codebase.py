"""Run the `analyze_codebase` workflow against a real directory.

Auth: uses the local Claude Code subscription via the `claude` CLI —
no ANTHROPIC_API_KEY is required.

Usage:
    python analyze_codebase.py <path-to-codebase> [options]

Options:
    --mock                  Skip the Claude CLI and use the mock executor
                            (deterministic stub — handy for offline runs).
    --mermaid               Add an extra step that produces a Mermaid
                            business-flow diagram for the codebase.
    --output-dir <path>     Root directory for outputs (default: ./output).
    --run-name <name>       Subdirectory under --output-dir (default:
                            <YYYYMMDD_HHMMSS>_<repo-name>).

Output layout (per run):
    output/<run-name>/
        README.md                 # index of this run
        scan.json                 # raw codebase walk
        01_inventory/inventory.md
        02_architecture/architecture.md
        03_quality/quality.md
        04_report/report.md
        05_diagram/diagram.md     # only with --mermaid
        05_diagram/diagram.mmd    # only with --mermaid (extracted code)
        checkpoint/<wf_id>.json   # orchestrator state — pass `--output-dir
                                  # output --run-name <wf_id>` to resume.

The default <run-name> is the workflow ID, so every artifact produced by
the run lives under a single, predictable directory.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# LLM responses routinely contain Unicode (arrows, quotes, etc.) — force
# utf-8 so Windows cp1252 stdout doesn't crash on `print`.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from agent_orchestrator import (
    AGENT_REGISTRY,
    Orchestrator,
    StepStatus,
    use_claude_code_for_all_agents,
)
from collections import Counter

from agent_orchestrator.agents import ClaudeCliNotFound
from agent_orchestrator.checkpoint import FileCheckpointStore
from agent_orchestrator.tools import _SKIP_DIRS, _classify, _walk_codebase
from agent_orchestrator.workflows import get_workflow_template
from agent_orchestrator.models import Step, Workflow, WorkflowStatus, new_id


DIAGRAM_INSTRUCTION = (
    "Produce ONE Mermaid flowchart that captures the business / data flow "
    "of this codebase: the main user- or service-facing operations and how "
    "data moves between modules. Use `flowchart TD` or `flowchart LR`. "
    "Identify clear actors, data stores, and decision points.\n\n"
    "Mermaid syntax rules you MUST follow:\n"
    "- Inside edge labels (the `|...|` between `-->` arrows) do NOT use "
    "`[`, `]`, `(`, `)`, `{`, `}` — Mermaid's parser treats them as node "
    "shapes and rejects the diagram. Rephrase the label in plain words "
    "(e.g. write `step output` instead of `step.output[name]`).\n"
    "- Use `<br/>` for line breaks inside labels, never raw newlines.\n"
    "- Keep node IDs simple ASCII (letters, digits, underscore).\n\n"
    "Return ONLY the Mermaid block — fenced as ```mermaid ... ``` — and "
    "no surrounding prose, headings, or commentary."
)


MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
MERMAID_PREFIXES = ("flowchart", "graph", "sequencediagram",
                    "classDiagram", "stateDiagram", "erDiagram")

# Characters that break Mermaid's parser when they appear inside a pipe-
# delimited edge label like `-->|some text|`. Mermaid sees `[` and starts
# expecting a node-shape close. We escape them to HTML entities, which
# Mermaid renders correctly inside labels.
_EDGE_LABEL_ESCAPES = {
    "[": "&#91;", "]": "&#93;",
    "(": "&#40;", ")": "&#41;",
    "{": "&#123;", "}": "&#125;",
}
_EDGE_LABEL_RE = re.compile(r"\|([^|\n]+)\|")


# --------------------------------------------------------------------------- feature scope

# Defaults chosen so a typical endpoint sweep stays well under any prompt-cache
# budget while still giving the LLM enough code to reason about.
_FEATURE_DEFAULTS = {
    "max_files": 30,           # cap matched files
    "full_content_kb": 30,     # files smaller than this go in full
    "context_lines": 8,        # excerpt window around each match
    "max_matches_per_file": 12,
}

# Skip files that are obviously not source code even if they happen to mention
# the query string (build artifacts, lockfiles, etc.).
_BINARY_OR_NOISE_EXTS = {
    ".lock", ".min.js", ".min.css", ".map", ".pyc", ".pyo", ".class",
    ".jar", ".war", ".dll", ".so", ".dylib", ".exe", ".bin", ".o",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar",
    ".gz", ".bz2", ".7z", ".woff", ".woff2", ".ttf", ".eot",
}

# Extend the package's general skip-list with directories this script itself
# tends to create — otherwise running the tool against its own repo turns up
# prior runs' checkpoints and output dirs as "feature matches".
_SCOPE_SKIP_DIRS = _SKIP_DIRS | {"output", ".checkpoints", ".agent_cache"}

# When restricting feature search to source code (the default), only these
# extensions and file names are considered. Anything else (JSON, YAML, MD,
# TOML, XML, ...) is excluded unless --include-non-source is passed.
_SOURCE_EXTS = {
    ".py", ".pyi",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".java", ".kt", ".scala", ".groovy",
    ".go", ".rs", ".rb", ".php", ".dart", ".swift",
    ".cs", ".fs", ".vb",
    ".c", ".h", ".hpp", ".cc", ".cpp", ".cxx", ".m", ".mm",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".sql",
    ".html", ".htm", ".vue", ".svelte",
    ".css", ".scss", ".sass", ".less",
    ".lua", ".r", ".jl", ".ex", ".exs", ".erl",
    ".clj", ".cljs", ".hs", ".elm", ".nim", ".zig",
}
_SOURCE_FILE_NAMES = {"Dockerfile", "Makefile", "Rakefile", "Gemfile"}


def _is_source_file(p: Path) -> bool:
    return p.suffix.lower() in _SOURCE_EXTS or p.name in _SOURCE_FILE_NAMES


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return None


def _excerpt(lines: list[str], match_idxs: list[int], context: int,
             max_matches: int) -> str:
    """Stitch context windows around match line indices into one snippet.
    Overlapping windows are merged so we don't repeat shared lines."""
    if not match_idxs:
        return ""
    windows: list[tuple[int, int]] = []
    for idx in match_idxs[:max_matches]:
        lo, hi = max(0, idx - context), min(len(lines), idx + context + 1)
        if windows and lo <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], hi))
        else:
            windows.append((lo, hi))
    chunks: list[str] = []
    for lo, hi in windows:
        chunks.append(
            "\n".join(f"{n+1:>5}: {lines[n]}" for n in range(lo, hi))
        )
    return "\n  ...\n".join(chunks)


def scope_by_feature(root: Path, query: str,
                     max_files: int | None = None,
                     full_content_kb: int | None = None,
                     context_lines: int | None = None,
                     max_matches_per_file: int | None = None,
                     extra_skip_dirs: set[str] | None = None,
                     include_non_source: bool = False) -> dict:
    """Find files referencing `query` (case-insensitive substring) and
    package only their content for downstream analysis.

    Unlike `_walk_codebase`, this never produces a listing of unrelated
    files — the returned `scan` dict contains *only* files that mention
    the feature, with full content (or context windows for large files).

    By default the walker (a) skips built-in noise dirs (`.git`, `node_modules`,
    `output`, `.checkpoints`, etc.) plus any names in `extra_skip_dirs`, and
    (b) only inspects files with source-code extensions. Pass
    `include_non_source=True` to grep JSON / YAML / Markdown / etc. as well.
    """
    max_files = max_files or _FEATURE_DEFAULTS["max_files"]
    full_content_kb = full_content_kb or _FEATURE_DEFAULTS["full_content_kb"]
    context_lines = context_lines if context_lines is not None else _FEATURE_DEFAULTS["context_lines"]
    max_matches_per_file = max_matches_per_file or _FEATURE_DEFAULTS["max_matches_per_file"]
    full_bytes = full_content_kb * 1024
    q_lower = query.lower()
    skip_dirs = _SCOPE_SKIP_DIRS | (extra_skip_dirs or set())

    matched: list[dict] = []
    skipped_too_many = False

    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if any(part in skip_dirs for part in f.parts):
            continue
        if f.suffix.lower() in _BINARY_OR_NOISE_EXTS:
            continue
        if not include_non_source and not _is_source_file(f):
            continue

        text = _read_text_safe(f)
        if text is None or q_lower not in text.lower():
            continue

        lines = text.splitlines()
        match_idxs = [i for i, line in enumerate(lines) if q_lower in line.lower()]
        if not match_idxs:
            continue

        size = f.stat().st_size
        if size <= full_bytes:
            content = text
            content_mode = "full"
        else:
            content = _excerpt(lines, match_idxs, context_lines, max_matches_per_file)
            content_mode = "excerpts"

        matched.append({
            "path": str(f.relative_to(root)).replace("\\", "/"),
            "language": _classify(f),
            "size_bytes": size,
            "match_count": len(match_idxs),
            "match_lines": match_idxs[:max_matches_per_file],
            "content_mode": content_mode,
            "content": content,
        })

        if len(matched) >= max_files:
            skipped_too_many = True
            break

    # Sort by relevance: most matches first, then by size as tiebreaker.
    matched.sort(key=lambda m: (-m["match_count"], m["size_bytes"]))

    langs = Counter(m["language"] for m in matched)
    total_bytes = sum(m["size_bytes"] for m in matched)

    return {
        "kind": "feature_scope",
        "path": str(root),
        "feature_query": query,
        "file_count": len(matched),
        "total_bytes": total_bytes,
        "languages": dict(langs.most_common()),
        "files": [m["path"] for m in matched],
        "matched_files": matched,
        "truncated": skipped_too_many,
        "scope_params": {
            "max_files": max_files,
            "full_content_kb": full_content_kb,
            "context_lines": context_lines,
            "max_matches_per_file": max_matches_per_file,
            "extra_skip_dirs": sorted(extra_skip_dirs or []),
            "include_non_source": include_non_source,
        },
    }


# --------------------------------------------------------------------------- symbol expansion

# Names so common they'd flood hop-2 results with false positives.
_SYMBOL_SKIP = {
    # Go stdlib packages
    "fmt", "os", "io", "net", "http", "time", "context", "errors", "log",
    "strings", "strconv", "bytes", "sync", "sort", "reflect", "json",
    "regexp", "math", "crypto", "encoding", "bufio", "path", "filepath",
    "url", "rand", "tls", "x509", "ioutil", "atomic", "rune",
    # Python stdlib
    "sys", "re", "typing", "datetime", "pathlib", "logging", "collections",
    "functools", "itertools", "asyncio", "subprocess", "argparse",
    # JS/TS globals
    "console", "process", "Buffer", "JSON", "Object", "Array", "String",
    "Number", "Promise", "Math", "Date", "Error", "Map", "Set", "Symbol",
    # Generic keywords / types
    "true", "false", "null", "nil", "self", "this", "string", "int", "bool",
    "float", "void", "var", "let", "const", "func", "return", "type",
    "package", "import", "from", "as", "def", "lambda", "interface",
    "struct", "class", "Test", "Mock", "Setup", "TearDown",
    # Generic verb / noun names (especially in Go/ORM code) — too common
    # to expand on; they'd pull in unrelated files via word-boundary match.
    "Get", "Set", "Add", "Remove", "Update", "Delete", "Create", "Find",
    "Insert", "Upsert", "Query", "Where", "Select", "Scan", "Wrap", "Use",
    "New", "Make", "Build", "Run", "Call", "Read", "Write", "Open", "Close",
    "Parse", "Format", "Print", "Println", "Marshal", "Unmarshal",
    "Encode", "Decode", "Hash", "Sign", "Verify",
    "Handler", "Middleware", "Router", "Request", "Response", "Context",
    "Result", "Status", "Config", "Options", "Client", "Server", "Service",
    "Manager", "Builder", "Factory", "Repository", "Controller",
    "Logger", "Tracer", "Metric", "Counter", "Gauge",
    "Bytes", "Time", "Duration", "Buffer", "Reader", "Writer", "Closer",
    "Filter", "Mapper", "Adapter", "Wrapper",
}

# Qualified names like `pkg.Symbol` or `pkg.Sub.Symbol`.
_QUALIFIED_NAME_RE = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
# Bare UpperCamelCase identifiers (likely function/type names).
_UPPER_CAMEL_RE = re.compile(r"\b[A-Z][a-z]\w{2,}\b")


def _focus_text(text: str, match_lines: list[int] | None,
                window: int = 10) -> str:
    """Return only the lines within ±`window` of any index in `match_lines`.
    If no match_lines provided, returns `text` unchanged."""
    if not match_lines:
        return text
    lines = text.splitlines()
    if not lines:
        return text
    keep: set[int] = set()
    for idx in match_lines:
        for j in range(max(0, idx - window), min(len(lines), idx + window + 1)):
            keep.add(j)
    return "\n".join(lines[j] for j in sorted(keep))


def _extract_symbols(text: str, top_n: int = 15,
                     match_lines: list[int] | None = None) -> list[str]:
    """Pull qualified names + bare UpperCamel identifiers from `text`.

    When `match_lines` is supplied (file is in 'full' content mode), the
    extraction is restricted to a ±10 line window around each match — this
    keeps hop-2 symbols tied to the actual feature usage instead of
    drowning in unrelated identifiers from elsewhere in the same file.

    Filters out single-letter heads (receiver vars like `r.Get`), stdlib
    packages, and language keywords. Returns the top-N by frequency — the
    tail segment of each name is what gets grep'd in the next hop.
    """
    focus = _focus_text(text, match_lines)
    counts: Counter[str] = Counter()

    for m in _QUALIFIED_NAME_RE.finditer(focus):
        name = m.group(0)
        head = name.split(".", 1)[0]
        if len(head) <= 1:           # `r.Get`, `e.GET`, ...
            continue
        if head in _SYMBOL_SKIP or head.lower() in _SYMBOL_SKIP:
            continue
        tail = name.rsplit(".", 1)[-1]
        if len(tail) < 4 or tail in _SYMBOL_SKIP:
            continue
        counts[tail] += 1

    for m in _UPPER_CAMEL_RE.finditer(focus):
        name = m.group(0)
        if name in _SYMBOL_SKIP or len(name) < 5:
            continue
        counts[name] += 1

    return [name for name, _ in counts.most_common(top_n)]


def _proximity_sorted(root: Path, seed_rel_paths: list[str]) -> list[Path]:
    """List every file under `root` ordered by directory proximity to the
    seed paths.

    Score per file = max over seeds of common path-prefix length with the
    seed's parent dir; ties broken alphabetically. Files in the SAME dir
    as a seed sort first; sibling dirs next; distant dirs last. This makes
    sure hop-N expansion reaches the obvious handler/service files before
    burning the file-count cap on unrelated areas of the repo.
    """
    seed_dirs = [Path(p).parent for p in seed_rel_paths]

    def score(f: Path) -> tuple[int, str]:
        try:
            rel_dir = f.relative_to(root).parent
        except ValueError:
            return (0, str(f))
        best = -1
        for sd in seed_dirs:
            # Bonus for exact dir match; otherwise count shared prefix parts.
            if rel_dir == sd:
                cand = 1000
            else:
                common = 0
                for a, b in zip(rel_dir.parts, sd.parts):
                    if a == b:
                        common += 1
                    else:
                        break
                # Penalize "depth past common" — a deeply nested unrelated
                # subtree should rank below a sibling at the same depth.
                cand = common * 10 - (len(rel_dir.parts) - common)
            if cand > best:
                best = cand
        return (-best, str(f))  # negative so higher score sorts first

    files = [f for f in root.rglob("*") if f.is_file()]
    files.sort(key=score)
    return files


def expand_feature_scope(
    initial_scan: dict,
    root: Path,
    hops: int,
    *,
    extra_skip_dirs: set[str] | None = None,
    include_non_source: bool = False,
    symbols_per_hop: int = 40,
) -> dict:
    """Run N symbol-based discovery hops after an initial feature scan.

    Each hop:
      1. Extract qualified / UpperCamel symbols from the current file set.
      2. Build a single word-boundary regex and grep the tree for any of them.
      3. Add newly-matched files (cap respects `_FEATURE_DEFAULTS['max_files']`).

    Returns a new scan dict — original input untouched.
    """
    if hops <= 0 or initial_scan.get("file_count", 0) == 0:
        return initial_scan

    hops = min(hops, 2)
    skip_dirs = _SCOPE_SKIP_DIRS | (extra_skip_dirs or set())
    max_total = initial_scan["scope_params"]["max_files"]
    full_bytes = initial_scan["scope_params"]["full_content_kb"] * 1024
    context_lines = initial_scan["scope_params"]["context_lines"]
    max_matches = initial_scan["scope_params"]["max_matches_per_file"]

    # Index everything we've matched so far by relative path.
    all_matched: dict[str, dict] = {
        m["path"]: dict(m, hop=m.get("hop", 0))
        for m in initial_scan["matched_files"]
    }
    # Files whose contents we'll mine for symbols this hop.
    current_paths = set(all_matched.keys())
    expand_log: list[dict] = []

    for hop in range(1, hops + 1):
        if len(all_matched) >= max_total:
            expand_log.append({
                "hop": hop, "symbols": [], "new_files": 0,
                "stopped": f"file cap ({max_total}) reached before hop {hop} "
                           "started — raise --feature-max-files to go deeper",
            })
            break
        symbol_counts: Counter[str] = Counter()
        for path_rel in current_paths:
            entry = all_matched[path_rel]
            content = entry.get("content", "") or ""
            # Only narrow by match_lines when we have the original full text;
            # excerpt mode already pre-trimmed the content to relevant windows.
            ml = entry.get("match_lines") if entry.get("content_mode") == "full" else None
            for sym in _extract_symbols(content, match_lines=ml):
                symbol_counts[sym] += 1
        candidates = [s for s, _ in symbol_counts.most_common(symbols_per_hop)]
        if not candidates:
            expand_log.append({"hop": hop, "symbols": [], "new_files": 0,
                               "stopped": "no symbols extracted"})
            break

        combined = re.compile(
            r"\b(?:" + "|".join(re.escape(s) for s in candidates) + r")\b"
        )

        # Iterate filesystem in proximity order so the cap is spent on the
        # files closest to where the feature actually lives, not whatever
        # comes first alphabetically.
        seed_paths_for_hop = list(all_matched.keys())
        candidate_files = _proximity_sorted(root, seed_paths_for_hop)

        # Reserve room for remaining hops so a chatty hop 1 doesn't starve
        # hop 2. Each remaining hop (including this one) gets an equal share
        # of the remaining cap.
        remaining_hops = hops - hop + 1
        hop_budget = max(1, (max_total - len(all_matched)) // remaining_hops)
        hop_cap = len(all_matched) + hop_budget

        newly_added: list[str] = []
        for f in candidate_files:
            if len(all_matched) >= hop_cap:
                break
            if not f.is_file():
                continue
            if any(part in skip_dirs for part in f.parts):
                continue
            if f.suffix.lower() in _BINARY_OR_NOISE_EXTS:
                continue
            if not include_non_source and not _is_source_file(f):
                continue

            rel = str(f.relative_to(root)).replace("\\", "/")
            if rel in all_matched:
                continue

            text = _read_text_safe(f)
            if text is None or not combined.search(text):
                continue

            lines = text.splitlines()
            match_idxs = [i for i, ln in enumerate(lines) if combined.search(ln)]
            if not match_idxs:
                continue

            size = f.stat().st_size
            if size <= full_bytes:
                content = text
                mode = "full"
            else:
                content = _excerpt(lines, match_idxs, context_lines, max_matches)
                mode = "excerpts"

            symbols_hit = sorted({m.group(0) for m in combined.finditer(text)})[:10]
            all_matched[rel] = {
                "path": rel,
                "language": _classify(f),
                "size_bytes": size,
                "match_count": len(match_idxs),
                "match_lines": match_idxs[:max_matches],
                "content_mode": mode,
                "content": content,
                "hop": hop,
                "symbols_matched": symbols_hit,
            }
            newly_added.append(rel)

        cap_hit = "global cap" if len(all_matched) >= max_total else (
            "hop budget" if len(all_matched) >= hop_cap else None
        )
        expand_log.append({
            "hop": hop,
            "symbols": candidates,
            "new_files": len(newly_added),
            "hop_budget": hop_budget,
            "stopped": cap_hit,
        })

        if not newly_added:
            break
        current_paths = set(newly_added)
        if len(all_matched) >= max_total:
            break

    # Sort: hop ascending (origin first), then by match_count desc, size asc.
    merged = sorted(
        all_matched.values(),
        key=lambda m: (m.get("hop", 0), -m["match_count"], m["size_bytes"]),
    )

    scan = dict(initial_scan)
    scan["matched_files"] = merged
    scan["files"] = [m["path"] for m in merged]
    scan["file_count"] = len(merged)
    scan["total_bytes"] = sum(m["size_bytes"] for m in merged)
    scan["languages"] = dict(Counter(m["language"] for m in merged).most_common())
    scan["expansion"] = {
        "hops_requested": hops,
        "hops_executed": len(expand_log),
        "per_hop": expand_log,
    }
    scan["scope_params"] = {**initial_scan["scope_params"], "expand_hops": hops}
    return scan


# --------------------------------------------------------------------------- mermaid

def sanitize_mermaid(code: str) -> str:
    """Escape characters inside edge labels that break Mermaid's parser.

    Only touches text between `|...|` on a single line — node-shape brackets
    elsewhere (e.g. `Foo[label]`, `Bar((label))`) are left alone.
    """
    def _fix(match: re.Match) -> str:
        body = match.group(1)
        # If the author already wrapped the label in quotes, trust them.
        if body.startswith('"') and body.endswith('"'):
            return f"|{body}|"
        for raw, esc in _EDGE_LABEL_ESCAPES.items():
            body = body.replace(raw, esc)
        return f"|{body}|"

    return _EDGE_LABEL_RE.sub(_fix, code)


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


# --------------------------------------------------------------------------- workflow

def build_workflow(scan: dict, with_diagram: bool) -> Workflow:
    """Materialize an `analyze_codebase` workflow and pre-seed the scan into
    workflow.context so the first step's `inputs_from` resolves.

    When `with_diagram` is True we append a fifth `diagram` step that asks
    the architect agent for a single Mermaid flowchart of the business flow.

    When the scan is a `feature_scope` (`--feature` mode), every step's
    instruction is rewritten so the LLM stays narrowly focused on that
    one feature instead of describing the surrounding codebase.
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
        request_payload={"path": scan["path"], "with_diagram": with_diagram},
        steps=steps,
    )
    wf.context["codebase_scan"] = scan
    return wf


# --------------------------------------------------------------------------- output

def _step_summary(step: Step) -> str:
    """Pull the assistant text out of a step's structured output."""
    if not step.output or not isinstance(step.output, dict):
        return ""
    agent_out = step.output.get("agent_output")
    if isinstance(agent_out, dict):
        return str(agent_out.get("summary") or "")
    return str(agent_out or "")


def extract_mermaid(text: str) -> str | None:
    """Pull a mermaid diagram out of an LLM response.

    Accepts a fenced ```mermaid block, or a bare diagram body (when the model
    obeyed our 'return ONLY the block' instruction but skipped the fence).
    Returns None if no plausible mermaid is found.
    """
    if not text:
        return None
    m = MERMAID_BLOCK.search(text)
    if m:
        return m.group(1).strip()
    stripped = text.strip().lstrip("`").strip()
    first_word = stripped.split(None, 1)[0] if stripped else ""
    if first_word.lower().startswith(tuple(p.lower() for p in MERMAID_PREFIXES)):
        return stripped
    return None


def _render_readme(
    wf: Workflow,
    scan: dict,
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
    scan: dict,
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
        agent_role = AGENT_REGISTRY[step.agent].role if step.agent in AGENT_REGISTRY else step.agent

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


# --------------------------------------------------------------------------- CLI

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("path", help="Path to the codebase directory to analyze.")
    ap.add_argument("--mock", action="store_true",
                    help="Use the built-in mock executor instead of the claude CLI.")
    ap.add_argument("--mermaid", action="store_true",
                    help="Add a Mermaid business-flow diagram step.")
    ap.add_argument("--feature", default=None,
                    help="Restrict analysis to files referencing this string "
                         "(e.g. '/v4/chartmonthly'). The codebase is NOT "
                         "walked in full — only matched files (and their "
                         "content) are sent to the LLM.")
    ap.add_argument("--feature-max-files", type=int, default=None,
                    help="Cap on matched files when --feature is set "
                         f"(default: {_FEATURE_DEFAULTS['max_files']}).")
    ap.add_argument("--exclude-dir", action="append", default=[],
                    metavar="NAME",
                    help="Additional directory name to skip during feature "
                         "search (repeatable). Built-in skips include "
                         ".git, node_modules, output, .checkpoints, etc.")
    ap.add_argument("--include-non-source", action="store_true",
                    help="Also grep non-source files (.json/.yaml/.md/.toml/"
                         "...). By default --feature only scans source code "
                         "extensions (.py/.ts/.go/.java/.html/.sql/...).")
    ap.add_argument("--expand", type=int, default=0, metavar="HOPS",
                    help="After the initial feature grep, run HOPS extra "
                         "passes that extract qualified / UpperCamel symbols "
                         "from matched files and grep the tree for them. "
                         "1 typically reaches handlers + middleware; 2 also "
                         "pulls in services / repos. Max 2. Default: 0.")
    ap.add_argument("--output-dir", default="output", type=Path,
                    help="Root directory for outputs (default: ./output).")
    ap.add_argument("--run-name", default=None,
                    help="Subdirectory name under --output-dir "
                         "(default: the workflow ID, e.g. wf_a9490452ebb4).")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    target = Path(args.path).resolve()
    if not target.exists() or not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return 2

    if args.feature:
        banner(f"SCOPING by feature  '{args.feature}'  under  {target}")
        # When --expand is used and the user didn't pick a cap, scale the
        # default with hops so deeper expansions actually have room to run.
        effective_max = args.feature_max_files
        if effective_max is None and args.expand > 0:
            effective_max = _FEATURE_DEFAULTS["max_files"] + 20 * args.expand
            print(f"auto cap     : --feature-max-files={effective_max} "
                  f"(scaled by --expand {args.expand})")
        scan = scope_by_feature(
            target,
            args.feature,
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

        if args.expand > 0:
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
        scan = _walk_codebase(target)
        top_langs = list(scan["languages"].items())[:8]
        print(f"files       : {scan['file_count']}")
        print(f"total bytes : {scan['total_bytes']:,}")
        print(f"languages   : {top_langs}")
        if scan["truncated"]:
            print(f"(file list truncated — showing first {len(scan['files'])})")

    if not args.mock:
        try:
            use_claude_code_for_all_agents()
            print("LLM         : claude CLI (subscription)")
        except ClaudeCliNotFound as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            print("Falling back to --mock mode.", file=sys.stderr)
            args.mock = True
    if args.mock:
        for a in AGENT_REGISTRY.values():
            a.executor = None
        print("LLM         : mock (deterministic stub)")

    # Build the workflow first so we know its ID — that becomes the default
    # run directory name, putting checkpoint + outputs under one folder.
    wf = build_workflow(scan, with_diagram=args.mermaid)
    run_name = args.run_name or wf.id
    run_dir = (args.output_dir / run_name).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"with diagram: {args.mermaid}")
    print(f"workflow id : {wf.id}")
    print(f"run dir     : {run_dir}")

    # Route the orchestrator's checkpoint into <run_dir>/checkpoint/<wf_id>.json
    # so every artifact produced by this run lives under run_dir.
    store = FileCheckpointStore(root=run_dir / "checkpoint")
    orch = Orchestrator(checkpoint_store=store)
    orch.checkpoints.save(wf)

    banner("RUNNING WORKFLOW analyze_codebase")
    wf = orch._execute(wf, on_step_start=on_start, on_step_end=on_end)

    banner(f"RESULT — status={wf.status.value}")
    for i, s in enumerate(wf.steps):
        marker = "OK" if s.status == StepStatus.SUCCESS else s.status.value.upper()
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

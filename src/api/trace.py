"""LLM-guided call-chain discovery.

Different from `expand_feature_scope` (which grabs every UpperCamel symbol
from a ±10 line window). Trace mode asks the LLM "given this entry point,
what classes/methods are actually called?" — then greps only those names.
The result is a much smaller, much more focused file set: only what's
in the request-handling call chain, not lexically-similar siblings.

One round = one extra LLM call. Default 2 rounds (entry-points → services
→ external clients). Cap ~20 files total.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.config import (
    BINARY_OR_NOISE_EXTS,
    SCOPE_SKIP_DIRS,
)
from src.llm.base import LLMProvider

from .scope import _excerpt, _read_text_safe, classify, is_source_file


_TRACE_SYSTEM_PROMPT = (
    "YOUR ENTIRE RESPONSE MUST BE A SINGLE JSON ARRAY AND NOTHING ELSE.\n"
    "No prose. No markdown headings. No bullet points. No fenced code block.\n"
    "Just the raw JSON array — starting with `[` and ending with `]`.\n\n"
    "Task: you are a call-graph analyzer. Given source code for the entry "
    "point of an HTTP endpoint, list EVERY class name, method name, or "
    "qualified call invoked as part of handling a request to this endpoint.\n\n"
    "Focus on:\n"
    "- Method invocations on injected services / repositories / clients "
    "(e.g. `customerService.findByBpNo(...)` -> name `findByBpNo`)\n"
    "- Class types in field declarations or constructor args "
    "(e.g. `private final AdminService adminService;` -> name `AdminService`)\n"
    "- External HTTP clients, message publishers, DB repositories\n"
    "- Conditional branches that route to different services\n"
    "- DTO / Entity types used in parameters or return values\n\n"
    "EXCLUDE:\n"
    "- Language keywords or stdlib types (String, Map, List, Optional, etc.)\n"
    "- Framework-only types (Mono, ResponseEntity, Controller, RestController)\n"
    "- Logging / metrics helpers unless they branch business logic\n\n"
    "Schema (each element):\n"
    '  {"name": "<identifier>", "kind": "<class|method|qualified>", '
    '"why": "<one-line reason>"}\n\n'
    "Cap at 20 identifiers. Most call-chain-critical first.\n\n"
    "REMINDER: output ONLY the JSON array. Your first character must be `[` "
    "and your last character must be `]`. Any prose or markdown will cause "
    "the parser to fail."
)


_JSON_BLOCK_RE = re.compile(r"\[[\s\S]*\]")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
# Fallback: when the model returns markdown prose instead of JSON, harvest
# any backtick-quoted identifier (\w[\w.]+ — letters/digits/dots, length >= 3).
_BACKTICK_IDENT_RE = re.compile(r"`([A-Za-z_][\w]*(?:\.[\w]+)*)`")
# Heuristic to skip framework / stdlib noise in the fallback path.
_FALLBACK_SKIP = {
    "String", "Map", "List", "Optional", "Mono", "Flux", "ResponseEntity",
    "Controller", "RestController", "Service", "Component", "Repository",
    "Autowired", "Inject", "Override", "Bean", "Configuration",
    "true", "false", "null", "nil", "void", "int", "boolean",
}


def _fallback_extract_identifiers(text: str) -> list[dict[str, str]]:
    """When JSON parsing fails, scrape backtick-quoted identifiers from prose.

    The model often returns text like:
       - `AdminController.getCustomer` — entry handler
       - `customerService.findByBpNo` — service call
    Pull those out, dedupe, and treat each as a kind='qualified' identifier.
    """
    counts: Counter[str] = Counter()
    for m in _BACKTICK_IDENT_RE.finditer(text):
        raw = m.group(1)
        tail = raw.rsplit(".", 1)[-1]
        if tail in _FALLBACK_SKIP or len(tail) < 3:
            continue
        counts[tail] += 1
    return [
        {"name": name, "full": name,
         "kind": "fallback",
         "why": "extracted from markdown prose (LLM ignored JSON instruction)"}
        for name, _ in counts.most_common(20)
    ]


def _build_trace_user_prompt(
    feature_query: str,
    known_files: dict[str, dict],
    round_n: int,
) -> str:
    parts = [
        f"# Endpoint under analysis\n`{feature_query}`",
        f"\n# Round {round_n}",
    ]
    if round_n == 1:
        parts.append(
            "List identifiers called from the entry-point file(s) below — "
            "the controllers / route handlers."
        )
    else:
        parts.append(
            "Previous round identified entry points and their immediate "
            "dependencies. This round: list identifiers called from those "
            "dependencies (services -> repositories -> external clients). "
            "Skip anything already-named in earlier rounds."
        )
    parts.append("\n# Source files (focus on uncovering call-chain identifiers)")
    for path, entry in sorted(known_files.items()):
        content = entry.get("content") or ""
        if len(content) > 8000:
            content = content[:8000] + "\n... (truncated)"
        parts.append(f"\n## `{path}` ({entry.get('language', '?')})\n```\n{content}\n```")
    return "\n".join(parts)


def _parse_identifiers(response: str) -> list[dict[str, str]]:
    """Pull the JSON array out of the LLM response.

    Tolerates: bare array, ```json ... ``` fenced array, prose around the array.
    Returns [] on parse failure — caller logs the raw response for inspection.
    """
    if not response:
        return []
    text = response.strip()

    # Prefer fenced JSON block if present — it's the most reliable signal.
    parsed = None
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            parsed = None

    if parsed is None:
        bracket_match = _JSON_BLOCK_RE.search(text)
        if bracket_match:
            try:
                parsed = json.loads(bracket_match.group(0))
            except (json.JSONDecodeError, ValueError):
                parsed = None

    if not isinstance(parsed, list) or not parsed:
        # JSON missing or empty — fall back to scraping backtick-quoted
        # identifiers from whatever prose the model returned.
        return _fallback_extract_identifiers(text)

    # Unwrap Claude content-block envelope `[{"type":"text","text":"..."}]`
    # — the real payload is the nested `text` string. Recurse once.
    if (len(parsed) == 1 and isinstance(parsed[0], dict)
            and "text" in parsed[0] and isinstance(parsed[0]["text"], str)):
        return _parse_identifiers(parsed[0]["text"])

    out: list[dict[str, str]] = []
    for item in parsed:
        # Accept both schemas: `{"name": "X", ...}` and bare string `"X"`.
        if isinstance(item, str):
            name_raw, kind, why = item, "unknown", ""
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            name_raw = item["name"]
            kind = str(item.get("kind") or "unknown")
            why = str(item.get("why") or "")
        else:
            continue
        name = name_raw.strip()
        # Strip method-call parens, qualifier prefixes for grep matching.
        tail = name.rsplit(".", 1)[-1].split("(", 1)[0].strip()
        if tail and len(tail) >= 3:
            out.append({
                "name": tail,
                "full": name,
                "kind": kind,
                "why": why,
            })
    # Dedupe by name.
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for it in out:
        if it["name"] in seen:
            continue
        seen.add(it["name"])
        deduped.append(it)
    return deduped


def _grep_identifiers(
    root: Path,
    identifiers: list[dict[str, str]],
    known_paths: set[str],
    *,
    max_new_files: int,
    full_content_kb: int = 30,
    context_lines: int = 8,
    max_matches_per_file: int = 12,
    extra_skip_dirs: set[str] | None = None,
    include_non_source: bool = False,
) -> list[dict[str, Any]]:
    """Word-boundary grep for any of `identifiers`. Returns new file entries.

    Prefers files where a definition is plausible (class/interface/func decl
    near the match) by ranking match_count + presence of `class <name>` or
    `def <name>` / `func <name>` patterns.
    """
    if not identifiers:
        return []
    skip_dirs = SCOPE_SKIP_DIRS | (extra_skip_dirs or set())
    full_bytes = full_content_kb * 1024

    names = [i["name"] for i in identifiers]
    combined = re.compile(
        r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b"
    )
    # Definition-ish patterns: `class Name`, `interface Name`, `func Name`,
    # `def Name`, `Name = (`/`Name :=`. Score these higher.
    defn_patterns = [
        re.compile(rf"(?:class|interface|struct|trait|enum|object)\s+(?:\w+\s+)?{re.escape(n)}\b")
        for n in names
    ] + [
        re.compile(rf"(?:func|def|fn|public|private|protected|static)?\s*\w*\s+{re.escape(n)}\s*\(")
        for n in names
    ]

    candidates: list[tuple[int, dict[str, Any]]] = []  # (score_negated, entry)
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if any(part in skip_dirs for part in f.parts):
            continue
        if f.suffix.lower() in BINARY_OR_NOISE_EXTS:
            continue
        if not include_non_source and not is_source_file(f):
            continue
        rel = str(f.relative_to(root)).replace("\\", "/")
        if rel in known_paths:
            continue

        text = _read_text_safe(f)
        if text is None or not combined.search(text):
            continue

        lines = text.splitlines()
        match_idxs = [i for i, ln in enumerate(lines) if combined.search(ln)]
        if not match_idxs:
            continue

        # Definition bonus: +50 per definition-ish match across the file text.
        defn_hits = sum(1 for p in defn_patterns if p.search(text))
        score = len(match_idxs) + 50 * defn_hits

        size = f.stat().st_size
        if size <= full_bytes:
            content = text
            mode = "full"
        else:
            content = _excerpt(lines, match_idxs, context_lines, max_matches_per_file)
            mode = "excerpts"

        symbols_hit = sorted({m.group(0) for m in combined.finditer(text)})[:10]
        entry = {
            "path": rel,
            "language": classify(f),
            "size_bytes": size,
            "match_count": len(match_idxs),
            "match_lines": match_idxs[:max_matches_per_file],
            "content_mode": mode,
            "content": content,
            "symbols_matched": symbols_hit,
            "definition_hits": defn_hits,
            "trace_score": score,
        }
        candidates.append((-score, entry))

    candidates.sort(key=lambda x: (x[0], x[1]["path"]))
    return [c[1] for c in candidates[:max_new_files]]


def llm_trace_discovery(
    scan: dict[str, Any],
    root: Path,
    provider: LLMProvider,
    *,
    max_rounds: int = 2,
    max_files: int = 20,
    extra_skip_dirs: set[str] | None = None,
    include_non_source: bool = False,
    on_round: callable | None = None,  # type: ignore[valid-type]
) -> dict[str, Any]:
    """Replace blind --expand symbol grep with LLM-curated call-chain discovery.

    Returns a new scan dict with files tagged by `hop` (0 for original grep,
    1+ for each trace round) plus an `expansion.per_hop` log compatible with
    the existing format.
    """
    if scan.get("file_count", 0) == 0:
        return scan
    feature = scan.get("feature_query", "(unspecified)")
    known: dict[str, dict[str, Any]] = {
        m["path"]: dict(m, hop=m.get("hop", 0))
        for m in scan["matched_files"]
    }
    expand_log: list[dict[str, Any]] = []

    for round_n in range(1, max_rounds + 1):
        if len(known) >= max_files:
            expand_log.append({
                "hop": round_n, "identifiers": [], "new_files": 0,
                "stopped": f"file cap ({max_files}) reached before round {round_n}",
            })
            break

        user_prompt = _build_trace_user_prompt(feature, known, round_n)
        try:
            response = provider.complete(_TRACE_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:  # noqa: BLE001
            expand_log.append({
                "hop": round_n, "identifiers": [], "new_files": 0,
                "stopped": f"LLM trace call failed: {type(exc).__name__}: {exc}",
            })
            break

        identifiers = _parse_identifiers(response)
        if on_round is not None:
            on_round(round_n, identifiers, response)
        if not identifiers:
            # Capture a snippet of the raw response so users can diagnose
            # the parse failure without re-running the trace.
            preview = (response or "").strip()[:300].replace("\n", " ")
            expand_log.append({
                "hop": round_n, "identifiers": [], "new_files": 0,
                "stopped": "no identifiers parsed from LLM response",
                "raw_response_preview": preview,
            })
            break

        new_files = _grep_identifiers(
            root, identifiers, set(known.keys()),
            max_new_files=max_files - len(known),
            extra_skip_dirs=extra_skip_dirs,
            include_non_source=include_non_source,
        )
        for entry in new_files:
            entry["hop"] = round_n
            entry["traced_via"] = [i["name"] for i in identifiers]
            known[entry["path"]] = entry

        expand_log.append({
            "hop": round_n,
            "identifiers": [i["name"] for i in identifiers],
            "new_files": len(new_files),
            "stopped": None,
        })
        if not new_files:
            break

    merged = sorted(
        known.values(),
        key=lambda m: (m.get("hop", 0),
                       -m.get("trace_score", m.get("match_count", 0)),
                       m["size_bytes"]),
    )
    out = dict(scan)
    out["matched_files"] = merged
    out["files"] = [m["path"] for m in merged]
    out["file_count"] = len(merged)
    out["total_bytes"] = sum(m["size_bytes"] for m in merged)
    out["languages"] = dict(Counter(m["language"] for m in merged).most_common())
    out["expansion"] = {
        "mode": "trace",
        "rounds_requested": max_rounds,
        "rounds_executed": len(expand_log),
        "per_hop": expand_log,
    }
    out.setdefault("scope_params", {})
    out["scope_params"]["trace_rounds"] = max_rounds
    out["scope_params"]["trace_max_files"] = max_files
    return out

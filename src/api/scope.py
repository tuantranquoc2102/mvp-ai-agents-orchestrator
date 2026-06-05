"""Codebase scoping — what files to send to the LLM.

Three entry points:
    walk_codebase(root)               full inventory (default mode)
    scope_by_feature(root, query)     literal-substring grep for an endpoint
                                      / function / config key
    expand_feature_scope(scan, hops)  N-hop symbol-based discovery —
                                      reaches handlers, services, repos
                                      from a single route declaration

None of these send file content to an LLM. They prepare a `scan` dict that
later workflow steps read as `codebase_scan` input.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.config import (
    BINARY_OR_NOISE_EXTS,
    EXT_TO_LANG,
    FEATURE_DEFAULTS,
    SCOPE_SKIP_DIRS,
    SKIP_DIRS,
    SOURCE_EXTS,
    SOURCE_FILE_NAMES,
    SYMBOL_SKIP,
)


# --------------------------------------------------------------------------- helpers

def classify(p: Path) -> str:
    if p.name in SOURCE_FILE_NAMES:
        return p.name.capitalize()
    return EXT_TO_LANG.get(p.suffix.lower(), p.suffix.lower() or "<no-ext>")


def is_source_file(p: Path) -> bool:
    return p.suffix.lower() in SOURCE_EXTS or p.name in SOURCE_FILE_NAMES


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return None


def _excerpt(lines: list[str], match_idxs: list[int], context: int,
             max_matches: int) -> str:
    """Stitch context windows around match line indices into one snippet.
    Overlapping windows are merged so shared lines aren't repeated."""
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


# --------------------------------------------------------------------------- full walk

def walk_codebase(root: Path, max_listed: int = 300) -> dict[str, Any]:
    """Inventory `root` for the default (no-feature) analysis mode.

    Returns a scan dict with file count, language distribution, total bytes,
    and a capped file list. Does NOT include file content — the inventory
    step works from the listing alone.
    """
    files: list[Path] = []
    for f in root.rglob("*"):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        if f.is_file():
            files.append(f)

    langs = Counter(classify(f) for f in files)
    total_bytes = sum(f.stat().st_size for f in files if f.exists())
    listed = sorted(str(f.relative_to(root)) for f in files)[:max_listed]
    return {
        "kind": "directory",
        "path": str(root),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "languages": dict(langs.most_common()),
        "files": listed,
        "truncated": len(files) > max_listed,
    }


# --------------------------------------------------------------------------- feature scope

def scope_by_feature(root: Path, query: str,
                     max_files: int | None = None,
                     full_content_kb: int | None = None,
                     context_lines: int | None = None,
                     max_matches_per_file: int | None = None,
                     extra_skip_dirs: set[str] | None = None,
                     include_non_source: bool = False) -> dict[str, Any]:
    """Find files referencing `query` (case-insensitive substring).

    Returns a scan dict containing only matched files, each with full content
    (if small) or context windows. The whole codebase is NOT listed.
    """
    max_files = max_files or FEATURE_DEFAULTS["max_files"]
    full_content_kb = full_content_kb or FEATURE_DEFAULTS["full_content_kb"]
    context_lines = context_lines if context_lines is not None else FEATURE_DEFAULTS["context_lines"]
    max_matches_per_file = max_matches_per_file or FEATURE_DEFAULTS["max_matches_per_file"]
    full_bytes = full_content_kb * 1024
    q_lower = query.lower()
    skip_dirs = SCOPE_SKIP_DIRS | (extra_skip_dirs or set())

    matched: list[dict[str, Any]] = []
    skipped_too_many = False

    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if any(part in skip_dirs for part in f.parts):
            continue
        if f.suffix.lower() in BINARY_OR_NOISE_EXTS:
            continue
        if not include_non_source and not is_source_file(f):
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
            "language": classify(f),
            "size_bytes": size,
            "match_count": len(match_idxs),
            "match_lines": match_idxs[:max_matches_per_file],
            "content_mode": content_mode,
            "content": content,
        })

        if len(matched) >= max_files:
            skipped_too_many = True
            break

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

_QUALIFIED_NAME_RE = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
_UPPER_CAMEL_RE = re.compile(r"\b[A-Z][a-z]\w{2,}\b")


def _focus_text(text: str, match_lines: list[int] | None,
                window: int = 10) -> str:
    """Return only lines within ±`window` of any index in `match_lines`."""
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

    When `match_lines` is supplied (full-mode content), extraction is
    restricted to a ±10 line window around each match — this keeps hop-N
    symbols tied to the actual feature usage instead of drowning in
    unrelated identifiers from elsewhere in the same file.
    """
    focus = _focus_text(text, match_lines)
    counts: Counter[str] = Counter()

    for m in _QUALIFIED_NAME_RE.finditer(focus):
        name = m.group(0)
        head = name.split(".", 1)[0]
        if len(head) <= 1:           # `r.Get`, `e.GET`, ...
            continue
        if head in SYMBOL_SKIP or head.lower() in SYMBOL_SKIP:
            continue
        tail = name.rsplit(".", 1)[-1]
        if len(tail) < 4 or tail in SYMBOL_SKIP:
            continue
        counts[tail] += 1

    for m in _UPPER_CAMEL_RE.finditer(focus):
        name = m.group(0)
        if name in SYMBOL_SKIP or len(name) < 5:
            continue
        counts[name] += 1

    return [name for name, _ in counts.most_common(top_n)]


def _proximity_sorted(root: Path, seed_rel_paths: list[str]) -> list[Path]:
    """List every file under `root` ordered by directory proximity to seeds.

    Files in the SAME dir as a seed sort first; sibling dirs next; distant
    dirs last. This makes hop-N expansion reach the obvious handler/service
    files before burning the cap on unrelated areas of the repo.
    """
    seed_dirs = [Path(p).parent for p in seed_rel_paths]

    def score(f: Path) -> tuple[int, str]:
        try:
            rel_dir = f.relative_to(root).parent
        except ValueError:
            return (0, str(f))
        best = -1
        for sd in seed_dirs:
            if rel_dir == sd:
                cand = 1000
            else:
                common = 0
                for a, b in zip(rel_dir.parts, sd.parts):
                    if a == b:
                        common += 1
                    else:
                        break
                cand = common * 10 - (len(rel_dir.parts) - common)
            if cand > best:
                best = cand
        return (-best, str(f))

    files = [f for f in root.rglob("*") if f.is_file()]
    files.sort(key=score)
    return files


def expand_feature_scope(
    initial_scan: dict[str, Any],
    root: Path,
    hops: int,
    *,
    extra_skip_dirs: set[str] | None = None,
    include_non_source: bool = False,
    symbols_per_hop: int = 40,
) -> dict[str, Any]:
    """Run N symbol-based discovery hops after an initial feature scan.

    Each hop:
      1. Extract qualified / UpperCamel symbols from the current file set.
      2. Build a single word-boundary regex and grep the tree for any of them.
      3. Add newly-matched files (cap respects `max_files`, with per-hop
         budget so a chatty hop 1 doesn't starve hop 2).
    """
    if hops <= 0 or initial_scan.get("file_count", 0) == 0:
        return initial_scan

    hops = min(hops, 2)
    skip_dirs = SCOPE_SKIP_DIRS | (extra_skip_dirs or set())
    max_total = initial_scan["scope_params"]["max_files"]
    full_bytes = initial_scan["scope_params"]["full_content_kb"] * 1024
    context_lines = initial_scan["scope_params"]["context_lines"]
    max_matches = initial_scan["scope_params"]["max_matches_per_file"]

    all_matched: dict[str, dict[str, Any]] = {
        m["path"]: dict(m, hop=m.get("hop", 0))
        for m in initial_scan["matched_files"]
    }
    current_paths = set(all_matched.keys())
    expand_log: list[dict[str, Any]] = []

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

        seed_paths_for_hop = list(all_matched.keys())
        candidate_files = _proximity_sorted(root, seed_paths_for_hop)

        # Reserve room for remaining hops — equal share of the remaining cap.
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
            if f.suffix.lower() in BINARY_OR_NOISE_EXTS:
                continue
            if not include_non_source and not is_source_file(f):
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
                "language": classify(f),
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

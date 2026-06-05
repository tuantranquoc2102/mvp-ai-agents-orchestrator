"""Mermaid extraction + post-processing.

The diagram step asks the LLM for a fenced ```mermaid block. We extract the
body, then sanitize it so the parser doesn't choke on characters the LLM
sometimes leaves inside edge labels (square brackets, parens, braces).
"""
from __future__ import annotations

import re

_MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_MERMAID_PREFIXES = ("flowchart", "graph", "sequencediagram",
                     "classDiagram", "stateDiagram", "erDiagram")

# Characters that break Mermaid's parser inside pipe-delimited edge labels.
_EDGE_LABEL_ESCAPES = {
    "[": "&#91;", "]": "&#93;",
    "(": "&#40;", ")": "&#41;",
    "{": "&#123;", "}": "&#125;",
}
_EDGE_LABEL_RE = re.compile(r"\|([^|\n]+)\|")


def extract_mermaid(text: str) -> str | None:
    """Pull a mermaid diagram out of an LLM response.

    Accepts a fenced ```mermaid block, or a bare diagram body (when the
    model obeyed 'return ONLY the block' but skipped the fence). Returns
    None when no plausible mermaid is found.
    """
    if not text:
        return None
    m = _MERMAID_BLOCK.search(text)
    if m:
        return m.group(1).strip()
    stripped = text.strip().lstrip("`").strip()
    first_word = stripped.split(None, 1)[0] if stripped else ""
    if first_word.lower().startswith(tuple(p.lower() for p in _MERMAID_PREFIXES)):
        return stripped
    return None


def sanitize_mermaid(code: str) -> str:
    """Escape characters inside `|...|` edge labels that break the parser.

    Idempotent — running it twice on the same string is a no-op. Quoted
    labels (`|"already quoted"|`) are left alone.
    """
    def _fix(match: re.Match) -> str:
        body = match.group(1)
        if body.startswith('"') and body.endswith('"'):
            return f"|{body}|"
        for raw, esc in _EDGE_LABEL_ESCAPES.items():
            body = body.replace(raw, esc)
        return f"|{body}|"

    return _EDGE_LABEL_RE.sub(_fix, code)

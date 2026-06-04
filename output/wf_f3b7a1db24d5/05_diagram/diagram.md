# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

[Software Architect] completed: Produce ONE Mermaid flowchart that captures the business / data flow of this codebase: the main user- or service-facing operations and how data moves between modules. Use `flowchart TD` or `flowchart LR`. Identify clear actors, data stores, and decision points.

Mermaid syntax rules you MUST follow:
- Inside edge labels (the `|...|` between `-->` arrows) do NOT use `[`, `]`, `(`, `)`, `{`, `}` — Mermaid's parser treats them as node shapes and rejects the diagram. Rephrase the label in plain words (e.g. write `step output` instead of `step.output[name]`).
- Use `<br/>` for line breaks inside labels, never raw newlines.
- Keep node IDs simple ASCII (letters, digits, underscore).

Return ONLY the Mermaid block — fenced as ```mermaid ... ``` — and no surrounding prose, headings, or commentary.

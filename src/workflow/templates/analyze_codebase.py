"""Analyze an arbitrary codebase (any language).

The caller (typically `src.api.cli`) is expected to pre-seed
`workflow.context["codebase_scan"]` with a walker output before submission.
"""
from ._helpers import step

REQUEST_TYPE = "analyze_codebase"

TEMPLATE = [
    step("inventory", "researcher",
         instruction=(
             "Summarize the codebase inventory: dominant languages, "
             "size, notable top-level files. Identify likely entry "
             "points and config/build files."
         ),
         inputs_from=["codebase_scan"]),
    step("architecture", "architect",
         instruction=(
             "Infer the architecture: layering, modules, external "
             "dependencies, and how the pieces communicate. Flag any "
             "structural smells (e.g. cyclic packages, god modules)."
         ),
         inputs_from=["codebase_scan", "inventory"]),
    step("quality", "reviewer",
         instruction=(
             "Assess code quality and risk: testing coverage signals, "
             "obvious security/footgun patterns, and maintainability "
             "concerns. Prioritize findings (high/medium/low)."
         ),
         inputs_from=["codebase_scan", "inventory", "architecture"]),
    step("report", "assistant",
         instruction=(
             "Write a final analysis report for an engineering lead. "
             "Sections: Overview, Architecture, Quality & Risk, "
             "Recommended Next Steps. Be specific; cite file paths "
             "from the inventory where useful."
         ),
         inputs_from=["inventory", "architecture", "quality"]),
]

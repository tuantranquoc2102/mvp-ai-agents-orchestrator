"""Research-only workflow (no code changes)."""
from ._helpers import step

REQUEST_TYPE = "research"

TEMPLATE = [
    step("scope", "cpo",
         instruction="Define what we need to learn and why."),
    step("investigate", "researcher", tool="search_web",
         instruction="Investigate prior art and viable options.",
         inputs_from=["scope"]),
    step("synthesis", "assistant", tool="write_doc",
         instruction="Synthesize findings into a recommendation memo.",
         inputs_from=["investigate"]),
]

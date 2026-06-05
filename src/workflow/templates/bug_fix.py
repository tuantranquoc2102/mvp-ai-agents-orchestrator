"""Quick bug fix workflow."""
from ._helpers import step

REQUEST_TYPE = "bug_fix"

TEMPLATE = [
    step("triage", "ba",
         instruction="Triage the bug report and reproduce the issue."),
    step("root_cause", "architect", tool="read_code",
         instruction="Locate root cause in the code.",
         inputs_from=["triage"]),
    step("patch", "fullstack", tool="write_code",
         instruction="Implement the fix.",
         inputs_from=["root_cause"]),
    step("regression_tests", "tester", tool="run_tests",
         instruction="Run regression suite.",
         inputs_from=["patch"]),
    step("review", "reviewer",
         instruction="Code-review the patch.",
         inputs_from=["patch", "regression_tests"]),
]

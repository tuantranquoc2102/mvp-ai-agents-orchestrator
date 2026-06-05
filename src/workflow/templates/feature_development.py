"""End-to-end feature build: exec sign-off through shipped feature."""
from ._helpers import step

REQUEST_TYPE = "feature_development"

TEMPLATE = [
    step("strategy_check", "ceo",
         instruction="Confirm the feature aligns with company strategy."),
    step("product_brief", "cpo", tool="write_doc",
         instruction="Draft a product brief and success metrics.",
         inputs_from=["strategy_check"]),
    step("requirements", "ba", tool="write_doc",
         instruction="Elicit and document functional requirements.",
         inputs_from=["product_brief"]),
    step("solution_design", "sa", tool="write_doc",
         instruction="Produce a solution design across systems.",
         inputs_from=["requirements"]),
    step("architecture", "architect", tool="write_doc",
         instruction="Define the technical architecture and interfaces.",
         inputs_from=["solution_design"]),
    step("plan", "pm", tool="create_ticket",
         instruction="Break work into tickets and milestones.",
         inputs_from=["architecture"]),
    step("backend_impl", "be_dev", tool="write_code",
         instruction="Implement backend services.",
         inputs_from=["architecture", "plan"]),
    step("frontend_impl", "fe_dev", tool="write_code",
         instruction="Implement frontend UI.",
         inputs_from=["architecture", "plan"]),
    step("tests", "tester", tool="run_tests",
         instruction="Write and run integration tests.",
         inputs_from=["backend_impl", "frontend_impl"]),
    step("review", "reviewer",
         instruction="Review the implementation; flag risks.",
         inputs_from=["backend_impl", "frontend_impl", "tests"]),
]

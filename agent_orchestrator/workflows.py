"""Static workflows keyed by request_type.

Each workflow is a list of StepTemplate dicts.  Orchestrator.submit() will
materialize these into concrete Step instances when a request comes in.

Keep this file declarative: no business logic, just the DAG-as-list.
"""
from __future__ import annotations

from typing import Any


def step(
    name: str,
    agent: str,
    *,
    tool: str | None = None,
    instruction: str = "",
    max_retries: int = 2,
    inputs_from: list[str] | None = None,
) -> dict[str, Any]:
    """Build a step template.

    `inputs_from` lists the names of prior step outputs to feed in as inputs
    (resolved at runtime from workflow.context).
    """
    return {
        "name": name,
        "agent": agent,
        "tool": tool,
        "instruction": instruction,
        "max_retries": max_retries,
        "inputs_from": inputs_from or [],
    }


WORKFLOW_REGISTRY: dict[str, list[dict[str, Any]]] = {
    # End-to-end feature build, exec sign-off -> shipped feature.
    "feature_development": [
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
    ],

    # Quick bug fix workflow.
    "bug_fix": [
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
    ],

    # Research-only workflow (no code changes).
    "research": [
        step("scope", "cpo",
             instruction="Define what we need to learn and why."),
        step("investigate", "researcher", tool="search_web",
             instruction="Investigate prior art and viable options.",
             inputs_from=["scope"]),
        step("synthesis", "assistant", tool="write_doc",
             instruction="Synthesize findings into a recommendation memo.",
             inputs_from=["investigate"]),
    ],

    # Analyze an arbitrary codebase (any language). The orchestrator's
    # caller is expected to pre-seed `workflow.context["codebase_scan"]`
    # with the output of tools._walk_codebase before submission — see
    # `analyze_codebase.py` for the wiring.
    "analyze_codebase": [
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
    ],

    # Strategic planning workflow.
    "strategy_review": [
        step("market_scan", "cso",
             instruction="Scan the competitive landscape."),
        step("product_pov", "cpo",
             instruction="Add product point of view.",
             inputs_from=["market_scan"]),
        step("ceo_decision", "ceo",
             instruction="Make the go/no-go call.",
             inputs_from=["market_scan", "product_pov"]),
    ],
}


def get_workflow_template(request_type: str) -> list[dict[str, Any]]:
    if request_type not in WORKFLOW_REGISTRY:
        raise KeyError(
            f"Unknown request_type: {request_type!r}. "
            f"Known: {sorted(WORKFLOW_REGISTRY)}"
        )
    # Return a shallow copy so callers can't mutate the registry.
    return [dict(s) for s in WORKFLOW_REGISTRY[request_type]]

"""Feature development — turn a task brief (free text / Jira ticket / file)
into a git branch, a rationale doc inside the source repo, and an LLM-produced
implementation plan.

Pipeline (the CLI in `src.api.feature_cli` may drop steps for BE-only /
FE-only / migration-only runs — see `applicable_steps` below):

    intake          BA      normalize the task brief (description + source dir + type)
    scope           SA      identify files / services the change will touch
    branch          PM      git_branch    create feature/<slug> in the source repo
    rationale       ARCH    write_rationale  drop docs/changes/<date>-<slug>.md
                                          (includes a logic-parity checklist
                                           when the run is a migration)
    architecture    ARCH    design the technical approach
    backend_plan    BE_DEV  plan backend edits (skipped for FE-only runs)
    frontend_plan   FE_DEV  plan frontend edits (skipped for BE-only runs)
    migration_audit ARCH    enumerate behaviors of service A vs B + deltas
                            (only when --migrate-from / --migrate-to are set)
    test_plan       TESTER  test strategy + risk areas
    review          REV     final risk review

The template stays static; per-run pruning lives in `applicable_steps()` so the
registry-driven discovery in `src.workflow.registry` keeps working unchanged.
"""
from __future__ import annotations

from typing import Any

from ._helpers import step

REQUEST_TYPE = "feature_development"


TEMPLATE: list[dict[str, Any]] = [
    step("intake", "ba",
         instruction=(
             "Read the task brief in `task_brief`. Restate it as a tight problem "
             "statement: goal, in-scope, out-of-scope, acceptance criteria. If "
             "the brief came from a Jira ticket, preserve the ticket id."
         ),
         inputs_from=["task_brief"]),
    step("scope", "sa",
         instruction=(
             "Using the intake summary and the `source_scan` snapshot of the "
             "target repository, list the files / modules / services this "
             "change is likely to touch. Group them by layer (api / service / "
             "repo / ui / config). Flag anything that looks risky."
         ),
         inputs_from=["intake", "source_scan"]),
    step("branch", "pm", tool="git_branch",
         instruction=(
             "Create a feature branch in the source repo. Name it from the "
             "task slug, prefixed by the task_type (feature/, migration/, "
             "bugfix/). The tool handles the actual `git checkout -b`."
         ),
         inputs_from=["intake"]),
    step("rationale", "architect", tool="write_rationale",
         instruction=(
             "Emit the FULL markdown body of the change-rationale doc, "
             "directly — no preamble, no 'I will write', no 'permission "
             "needed', no path discussion. Treat your output as the file "
             "contents that will be saved verbatim. Required sections "
             "(use these as H2 headings): `## Why` (business + technical "
             "motivation), `## What changes` (scope summary), `## Out of "
             "scope`, `## Acceptance criteria`, and `## Logic-parity "
             "checklist` — the last section is REQUIRED when migrating "
             "between services / languages / frameworks: list each "
             "behavior of the source side and the equivalent on the "
             "target side as a markdown table with columns `behavior`, "
             "`source impl`, `target impl`, `status (preserved / changed "
             "/ deprecated)`, `risk`."
         ),
         inputs_from=["intake", "scope"]),
    step("architecture", "architect",
         instruction=(
             "Lay out the technical approach: data model touches, API "
             "contracts, sequence of operations, error handling. Reference "
             "concrete file paths from the scope. Keep it implementable, "
             "not aspirational."
         ),
         inputs_from=["intake", "scope", "rationale"]),
    step("backend_plan", "be_dev",
         instruction=(
             "Produce a backend implementation plan: list of files to "
             "create / modify, function signatures, db migrations, "
             "external calls. Do NOT write code — produce the plan a "
             "developer will execute on the feature branch."
         ),
         inputs_from=["architecture"]),
    step("frontend_plan", "fe_dev",
         instruction=(
             "Produce a frontend implementation plan: components, state, "
             "API calls, routing, copy. List files to create / modify. "
             "Do NOT write code — produce the plan a developer will "
             "execute on the feature branch."
         ),
         inputs_from=["architecture"]),
    step("migration_audit", "architect",
         instruction=(
             "Migration logic-parity audit. You have file listings for "
             "BOTH sides: `migrate_from_scan` (the source/legacy repo) and "
             "`source_scan` (the target/destination repo where new code "
             "lands). For each behavior of the SOURCE side, state the "
             "equivalent behavior on the TARGET side. Output a markdown "
             "table with columns: behavior, source files, target files, "
             "status (preserved / changed / dropped), risk. Cite specific "
             "file paths from the scans. Flag any silent behavior change "
             "as HIGH risk."
         ),
         inputs_from=["intake", "scope", "rationale", "architecture",
                      "migrate_from_scan", "source_scan"]),
    step("test_plan", "tester",
         instruction=(
             "Test strategy for the change. Unit, integration, e2e — call "
             "out which layers each touches. List the regression risks "
             "(especially for migrations: golden-output tests that pin "
             "current behavior of the SOURCE side, then run against TARGET)."
         ),
         inputs_from=["architecture", "backend_plan", "frontend_plan",
                      "migration_audit"]),
    step("review", "reviewer",
         instruction=(
             "Final review pass over the full plan. Surface unresolved "
             "questions, missing test coverage, and anything the rationale "
             "doc didn't justify. Output a numbered risk list, highest "
             "first."
         ),
         inputs_from=["rationale", "architecture", "backend_plan",
                      "frontend_plan", "migration_audit", "test_plan"]),
]


# Steps the CLI keeps for a given task type. Anything not listed is dropped
# from the workflow before instantiation. The CLI also drops `migration_audit`
# unless --migrate-from / --migrate-to are set.
TASK_TYPE_STEPS: dict[str, set[str]] = {
    "backend": {
        "intake", "scope", "branch", "rationale", "architecture",
        "backend_plan", "test_plan", "review",
    },
    "frontend": {
        "intake", "scope", "branch", "rationale", "architecture",
        "frontend_plan", "test_plan", "review",
    },
    "fullstack": {
        "intake", "scope", "branch", "rationale", "architecture",
        "backend_plan", "frontend_plan", "test_plan", "review",
    },
    "migration": {
        "intake", "scope", "branch", "rationale", "architecture",
        "backend_plan", "frontend_plan", "migration_audit",
        "test_plan", "review",
    },
}


def applicable_steps(
    task_type: str,
    *,
    is_migration: bool = False,
) -> list[dict[str, Any]]:
    """Return a fresh template list filtered for this run.

    `task_type` picks the base step set. `is_migration` (set when the user
    passed --migrate-from / --migrate-to even on a non-"migration" task type)
    forces `migration_audit` back in. Always returns deep-enough copies that
    the caller can mutate without touching `TEMPLATE`.
    """
    base = TASK_TYPE_STEPS.get(task_type)
    if base is None:
        raise ValueError(
            f"unknown task_type {task_type!r}; "
            f"expected one of {sorted(TASK_TYPE_STEPS)}"
        )
    keep = set(base)
    if is_migration:
        keep.add("migration_audit")
    else:
        keep.discard("migration_audit")
    return [dict(s) for s in TEMPLATE if s["name"] in keep]

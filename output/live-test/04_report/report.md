# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report: `agent_orchestrator`

**Prepared for:** Engineering Lead
**Date:** 2026-06-02
**Subject:** MVP review of the Python agent-orchestration package at `F:\03_POC_PROJECTS\claude\agent_orchestrator`

---

## 1. Overview

`agent_orchestrator` is a small (~38 KB, 8 files), stdlib-only Python package that implements a **registry-driven workflow engine** wrapping the `claude` CLI. It exposes a single programmatic entry point — the `Orchestrator` class re-exported from `__init__.py` — and is intended to be consumed as a library, not run as a standalone application (no `__main__.py`, no CLI shim, no script shebangs).

The system is organized around three static registries declared at import time:

- `AGENT_REGISTRY` in `agents.py` — agent definitions plus the Claude Code subprocess executor.
- `WORKFLOW_REGISTRY` in `workflows.py` — declarative step templates keyed by request type (e.g. `feature_development`).
- `TOOL_REGISTRY` in `tools.py` — callable tools that agents may invoke, guarded by a per-agent permission check.

State machine semantics are provided by `models.py` (`Step`, `Workflow`, `StepStatus`, `WorkflowStatus`), and durability comes from `checkpoint.py`, which writes workflow state to JSON via an atomic `os.replace`. The execution loop lives in `runner.py` and is invoked from `core.py` (`Orchestrator.submit` / `Orchestrator.resume`).

**Maturity assessment:** Functional MVP. The skeleton is coherent and the layering is genuinely clean, but the package lacks the production scaffolding (packaging metadata, dependency pinning, tests, CI, README) needed to ship or distribute. There is no `pyproject.toml`, `setup.py`, `requirements.txt`, `README.md`, `Dockerfile`, or CI config in the tree.

---

## 2. Architecture

### 2.1 Layering

The package is organized into four layers with strictly downward imports — a real Clean/Hexagonal-leaning structure rather than a cosmetic one:

| Layer | Modules | Responsibility |
|---|---|---|
| Public API (facade) | `__init__.py` | Re-exports `Orchestrator`, the three registries, and the domain models. |
| Orchestration (use cases) | `core.py` (`Orchestrator`) | Submits new workflows, resumes from checkpoints, persists state. |
| Execution (step engine) | `runner.py` (`run_step`) | Retry loop, calls `agent.execute`, dispatches `invoke_tool`. |
| Domain & registries | `models.py`, `agents.py`, `tools.py`, `workflows.py`, `checkpoint.py` | Pure data, registries, and the `CheckpointStore` Protocol with a file-based implementation. |

The leaves (`models.py`, `workflows.py`, `checkpoint.py`) have no internal upward dependencies, which is the right shape for a layered system.

### 2.2 Module dependency graph

```
__init__ ─► core ─► agents (subprocess → `claude` CLI)
            │
            ├─► runner ─► agents
            │         └─► tools ─► agents     ← coupling hot-spot
            │
            ├─► checkpoint ─► models
            ├─► workflows  (pure data)
            └─► models     (pure data, leaf)
```

- **Hub module:** `agents.py` (~10.3 KB) is imported by `core`, `runner`, and `tools`. It is both the largest file and the most-depended-on internal module — any change here has the widest blast radius.
- **External dependencies:** stdlib only (`dataclasses`, `enum`, `uuid`, `json`, `pathlib`, `subprocess`, `shutil`, `os`, `traceback`, `datetime`, `typing`). The single out-of-process dependency is the `claude` binary, discovered at runtime via `shutil.which`.

### 2.3 Communication patterns

| From → To | Mechanism |
|---|---|
| Caller → `Orchestrator.submit/resume` | Direct method call returning a `Workflow`. |
| `core` → `workflows` | Template lookup in `WORKFLOW_REGISTRY`. |
| `core` → `runner` | In-process call; **`Step` is mutated in place**. |
| `runner` → `agent` | Pluggable `Callable` (mock or `claude_code_executor`). |
| `agent` → Claude | `subprocess.run(['claude', '--print', …])`, 300 s default timeout. |
| `runner` → `tools` | Permission gate, then dispatch via `TOOL_REGISTRY`. |
| `core` → `checkpoint` | JSON file persisted with atomic `os.replace`. |
| Step → Step (data flow) | `inputs_from=[…]` resolved against `workflow.context[step.name]` in `runner._resolve_inputs`. |

### 2.4 Execution model

- **Strictly sequential.** `runner` iterates `for i in range(current_step_idx, len(steps))` — there is no DAG scheduler and no concurrency, even where the declared `inputs_from` graph in `workflows.py` (e.g. `backend_impl` and `frontend_impl` in `feature_development`) would permit parallel fan-out.
- **Recovery model.** On resume, execution rewinds to the first non-terminal step. This is simple and safe but re-runs work for any step that wasn't atomic.
- **Pluggability.** The `agent.execute` callable and the `CheckpointStore` Protocol are the two seams designed for substitution; both are exercised by the in-tree mock executor.

---

## 3. Quality & Risk

### 3.1 Strengths

- **Clean layering, honestly enforced.** Import direction is one-way; the leaf modules are pure data. This is rare in MVPs and worth preserving.
- **Stdlib-only.** Zero supply-chain surface today. Easy to vendor or embed.
- **Durable-by-default.** Atomic checkpoint write via `os.replace` in `checkpoint.py` avoids torn-write corruption on resume.
- **Test seams exist.** The pluggable executor and `CheckpointStore` Protocol mean unit tests can be added without refactoring.

### 3.2 Risks and smells

1. **`tools.py` depends on `agents.py` for permission checks** (the coupling hot-spot in the dependency graph). Conceptually, tool permissions are policy about agents, not a property of the tool registry. Today this is benign; it becomes a circular-dependency risk the moment agents need to know which tools they own.
2. **`agents.py` is a god module.** At 10.3 KB it carries agent definitions, the registry, *and* the `claude` subprocess executor. The executor is an infrastructure concern (process I/O, timeout, stdout parsing) and should live in its own module so `agents.py` can stay declarative.
3. **No concurrency despite a declared DAG.** `workflows.py` encodes parallelizable branches via `inputs_from`, but `runner.py` ignores the structure and runs sequentially. This is a latent feature, not a bug, but it's the most obvious next architectural lever.
4. **In-place `Step` mutation in `runner.run_step`.** Convenient, but it means any future concurrent executor will need either copy-on-write or locking. Better to surface this constraint now.
5. **Subprocess fragility.** `agents.py` shells out to the `claude` binary with a 300 s default timeout and no structured error taxonomy. Failure modes (binary missing, timeout, non-zero exit, malformed stdout) all collapse into generic exceptions in the retry loop. There is no rate limiting, no backoff jitter, and no cost/usage telemetry.
6. **No tests, no CI, no packaging.** The directory contains only `.py` files and `__pycache__/`. There is no way to verify a change short of running an integration that actually invokes `claude`. This is the single biggest delivery risk.
7. **No dependency pinning.** Stdlib-only today, but the Python version itself is unpinned. A `pyproject.toml` with `requires-python` is a 10-minute fix that prevents subtle `dataclasses`/`typing` regressions on older interpreters.
8. **Checkpoint format is unversioned.** `checkpoint.py` serializes `Workflow`/`Step` as JSON with no schema version field. Any change to `models.py` becomes a silent migration hazard for in-flight workflows.
9. **No structured logging or tracing.** `runner.py` and `agents.py` use plain exceptions and (likely) `print`/`traceback`. For a workflow engine, the ability to replay a single step's input/output deterministically is table stakes — and it is missing.
10. **Security/permission gate is shallow.** `tools.py` checks whether an agent is allowed to call a tool, but there is no scoping on the *arguments* passed in. A tool with filesystem access permitted for any agent is permitted for *any path*.

### 3.3 Severity summary

| Risk | Severity | Likelihood |
|---|---|---|
| No tests / CI | **High** | Certain |
| Subprocess error handling in `agents.py` | High | High |
| `agents.py` god module | Medium | Certain |
| Unversioned checkpoint schema | Medium | Medium (on first model change) |
| Sequential-only executor vs. declared DAG | Medium | Low (perf, not correctness) |
| Tool permission scope | Medium | Depends on tool set |
| Missing packaging metadata | Low | Certain |

---

## 4. Recommended Next Steps

Ordered by ratio of value to effort.

### Near term (this sprint)

1. **Add a minimum test harness.** Stand up `pytest` with two suites: (a) unit tests against `runner.py`, `core.py`, `checkpoint.py`, and the registries using the existing mock executor; (b) a single integration test that stubs `subprocess.run` to validate `agents.py`'s executor parses stdout and honors the 300 s timeout. Target: ≥70 % line coverage on `core.py`, `runner.py`, `checkpoint.py`, `models.py` before any further feature work.
2. **Add packaging.** Create `pyproject.toml` with `requires-python`, project metadata, and an explicit (empty for now) dependency list. Add a `README.md` describing the `Orchestrator.submit/resume` API and the registry-extension pattern.
3. **Split `agents.py`.** Move the Claude subprocess executor into a new `executors.py` (or `infrastructure/claude_executor.py`). Keep `agents.py` declarative: `Agent` dataclass, registry, allowed-tools metadata. This shrinks the hub module and makes alternative executors (HTTP, mock, recorded-replay) first-class.
4. **Version the checkpoint format.** Add a `schema_version: int` field in `checkpoint.py`'s serialized payload and a guard on load. Even a hard-fail-on-mismatch is better than silent breakage.

### Medium term (next 2–4 weeks)

5. **Strengthen the subprocess boundary in `agents.py`.** Introduce a small error taxonomy (`ExecutorTimeout`, `ExecutorMissing`, `ExecutorNonZeroExit`, `ExecutorOutputParseError`) and surface these to `runner.py` so retry policy can be per-failure-class instead of blanket.
6. **Invert the `tools → agents` dependency.** Move per-agent allowed-tool lists onto the `Agent` dataclass (or into `workflows.py` step metadata) so `tools.py` only knows about *tools*. This eliminates the lone upward-pointing edge in the dependency graph.
7. **Add structured logging + per-step trace records.** At minimum, log step name, attempt number, executor inputs, outputs, and duration to a JSONL sidecar alongside the checkpoint. This unlocks debugging without re-running the `claude` binary.
8. **Add a CI workflow.** GitHub Actions (or equivalent) running lint (`ruff`), type-check (`mypy --strict` is realistic given the stdlib-only surface), and the test suite on push.

### Longer term (when the use case demands it)

9. **DAG executor.** Honor `inputs_from` in `runner.py` and run independent steps concurrently via `concurrent.futures` or `asyncio`. Required precursor: replace in-place `Step` mutation with explicit returned step results.
10. **Pluggable checkpoint backends.** The `CheckpointStore` Protocol already exists in `checkpoint.py`; add a SQLite implementation. JSON-on-disk is fine for one process but unsafe under any concurrency.
11. **Argument-level tool permissions.** Extend the `tools.py` permission gate to accept a predicate over arguments, not just a boolean per (agent, tool) pair.
12. **Cost & rate-limit observability.** Capture token usage and wall-clock per `claude` invocation in `agents.py`'s executor and aggregate at the workflow level in `core.py`.

---

**Bottom line for the lead:** The architecture is genuinely sound for an MVP — the layering is clean, the seams for substitution are in the right places, and the stdlib-only footprint is a feature. The gap between this and a shippable library is **not** architectural rework; it is the missing engineering hygiene layer (tests, CI, packaging, structured errors, checkpoint versioning). Investing one focused sprint on items 1–4 above will de-risk everything that follows.

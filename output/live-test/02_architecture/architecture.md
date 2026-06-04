# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis: `agent_orchestrator`

## 1. Layering (Clean / Hexagonal-leaning)

The package separates into four well-defined layers. Imports flow strictly downward — no upward references — which is the cleanest signal in the codebase.

```
┌──────────────────────────────────────────────────────────┐
│  Public API  ── __init__.py                              │  (facade)
├──────────────────────────────────────────────────────────┤
│  Orchestration ── core.Orchestrator                      │  (use cases)
│        submits / resumes workflows, persists state       │
├──────────────────────────────────────────────────────────┤
│  Execution    ── runner.run_step                         │  (step engine)
│        retry loop, agent.execute → invoke_tool dispatch  │
├──────────────────────────────────────────────────────────┤
│  Domain & Registries                                     │
│   ├── models   (Step, Workflow, *Status)  ── pure data   │
│   ├── agents   (Agent, AGENT_REGISTRY, executors)        │
│   ├── tools    (Tool, TOOL_REGISTRY, permission gate)    │
│   ├── workflows (WORKFLOW_REGISTRY templates)            │
│   └── checkpoint (CheckpointStore Protocol + File impl.) │
└──────────────────────────────────────────────────────────┘
```

## 2. Module dependency graph

```
__init__  ─►  core ─► agents ─► (stdlib only: subprocess, shutil, json)
                │
                ├─► runner ─► agents
                │           └► tools  ─► agents      ← see smell #1
                │
                ├─► checkpoint ─► models
                ├─► workflows  (pure data)
                └─► models     (pure data, leaf)
```

- **Leaves:** `models.py` (no internal deps), `workflows.py` (pure templates), `checkpoint.py` (depends only on `models`).
- **Hub:** `agents.py` is imported by `core`, `runner`, and `tools` — it's the most-depended-on internal module.
- **External deps:** **stdlib only** (`dataclasses`, `enum`, `uuid`, `json`, `pathlib`, `subprocess`, `shutil`, `os`, `traceback`, `datetime`, `typing`). The only out-of-process dependency is the `claude` CLI binary discovered via `shutil.which`. No `requirements.txt`/`pyproject.toml` is present — appropriate for a stdlib-only MVP but worth pinning before distribution.

## 3. How the pieces communicate

| From | To | Mechanism |
|---|---|---|
| Caller | `Orchestrator.submit(request_type, payload)` | function call returning `Workflow` |
| `core` → `workflows` | `get_workflow_template` | lookup in `WORKFLOW_REGISTRY` |
| `core` → `runner` | `run_step(step, agent, context)` | in-process call, **mutates `Step` in place** |
| `runner` → `agent` | `agent.execute(instruction, inputs, context)` | pluggable `Callable` (mock or `claude_code_executor`) |
| `agent` → Claude | `subprocess.run(['claude', '--print', …])` | OS process, stdin/stdout, 300 s default timeout |
| `runner` → `tools` | `invoke_tool(agent, tool_name, **kwargs)` | permission check then dispatch |
| `core` → `checkpoint` | `CheckpointStore.save/load` | JSON file written atomically via `os.replace` |
| Step → Step (data flow) | `inputs_from=[…]` → `workflow.context[step.name]` | shared dict keyed by step name, resolved at runtime in `_resolve_inputs` |

Step ordering is **strictly sequential** (`for i in range(current_step_idx, len(steps))`). There is no DAG executor and no concurrency, even where `inputs_from` would permit parallel branches (e.g. `backend_impl` and `frontend_impl` in `feature_development`). Recovery is "rewind to the first non-terminal step." The pluggable `CheckpointStore` Protocol leaves room to swap in Redis/S3/DB without touching `core`.

## 4. Structural smells

| Severity | Smell | Location | Notes |
|---|---|---|---|
| **Medium** | **Latent circular-import risk** between `agents` and `tools` | `tools.py:14` imports `Agent` from `agents`; the comment in `agents.py:27-28` admits the risk and works around it by keeping tool names as bare strings. Fine today, but adding any `from .tools import …` to `agents.py` will break the package. Consider extracting a tiny `permissions.py` or moving `Agent` into `models.py` to make the boundary explicit. |
| **Medium** | **`agents.py` is becoming a god-module** (10.3 KB, ~300 lines) | mixes 4 concerns: the `Agent` dataclass, the 14-entry registry, the mock executor, and the entire Claude CLI subprocess driver (`_find_claude_cli`, `_build_*_prompt`, `claude_code_executor`, `use_claude_code_for_all_agents`). Split into `agents/registry.py` + `agents/executors/claude_cli.py`. |
| **Medium** | **Shared mutable `workflow.context`** is a god-bag passed by reference through every layer (`core._execute` → `runner.run_step` → `agent.execute`). Any step can write any key. Workable at MVP scale, but invites action-at-a-distance once executors are real LLMs. Consider a read-only view + an explicit "outputs" return channel. |
| **Medium** | **Tool kwargs come from `step.inputs`** (`runner.py:65`), which is the upstream-step output blob, not anything the agent chose. The MVP comment owns this, but it means `_write_doc("path", content="…")` is effectively never called with the right kwargs — the tool layer is decorative until an agent-driven kwarg-selection step is added. |
| **Low** | **No DAG, but `inputs_from` already encodes one.** `feature_development` lists `backend_impl` and `frontend_impl` with the same `inputs_from=["architecture", "plan"]` — they could run in parallel but execute serially. Either drop `inputs_from`'s precision or upgrade the runner to topological. |
| **Low** | **`workflows.py` has no validation.** A typo in `inputs_from=["architectur"]` silently produces an empty input dict (see `core._resolve_inputs`); the step still "succeeds." Add a `_validate_template` pass at registry-build time. |
| **Low** | **Status enum drift risk.** `Step.status` accepts a `SKIPPED` value, but no code path ever sets it. Either wire it up (e.g. on a permission-denied non-fatal step) or remove it. |
| **Low** | **`runner.run_step` uses `callable` (builtin) as a type hint** (`runner.py:28`) — the `# type: ignore` is a giveaway. Use `Callable[[Step], None] | None` from `typing`. |
| **Low** | **Mixed responsibility in `core._resolve_inputs`** — it `pop`s the sentinel key (mutation) every time the step runs; safe today because `SUCCESS` short-circuits the loop, but fragile if retries are ever moved out of `runner`. |
| **Low** | **No unit tests, no CI, no `pyproject.toml`.** Inventory confirmed zero config files. For a state-machine MVP this is the highest-leverage gap — the design clearly anticipates swappable `CheckpointStore` and `executor`, both of which are exactly what you want to fake in tests. |

## 5. Strengths worth preserving

- **Protocol-based seam** for `CheckpointStore` and the `executor` callable on `Agent` — both are textbook ports/adapters and make the engine testable without mocks-on-mocks.
- **Atomic checkpoint writes** via temp-file + `os.replace` (`checkpoint.py:39-41`).
- **Least-privilege tool allowlists** per agent (`agents.py:88-176`), validated at dispatch in `tools.check_permission`.
- **Declarative workflows** (`workflows.py`) keep the DAG-as-data, so the engine never sees domain logic — a clean inversion.
- **Public surface is small and explicit** (`__init__.py` `__all__`), so the "swap the inner loop for an async runner later" promise in `core.py:11-13` is realistic.

## 6. Top three architectural moves

1. **Split `agents.py`** into `agents/registry.py` (dataclass + registry + mock executor) and `agents/executors/claude_cli.py` (subprocess driver). Eliminates the god-module trend and quarantines the only IO-heavy code in the project.
2. **Promote the step-DAG to a real DAG executor.** `inputs_from` already encodes dependencies — a `TopologicalRunner` would yield parallelism on `feature_development` for free and is a natural place to introduce `asyncio`.
3. **Add a workflow-template validator** (executed at import time) that asserts every `agent` name exists in `AGENT_REGISTRY`, every `tool` exists in `TOOL_REGISTRY` and is in the agent's allowlist, and every `inputs_from` references a prior step's `name`. Catches the most common authoring mistakes before any step runs.

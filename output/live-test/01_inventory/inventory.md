# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

## Codebase Inventory Summary

**Path:** `F:\03_POC_PROJECTS\claude\agent_orchestrator`

### Dominant Language
- **Python (100%)** — 8 source files, no other languages detected.

### Size
- **Total:** ~38 KB across 8 Python files (small, MVP-scale module).
- Largest files: `agents.py` (10.3 KB), `workflows.py` (6.6 KB), `tools.py` (6.4 KB), `core.py` (5.9 KB).

### Notable Top-Level Files & Likely Roles
| File | Size | Likely Purpose |
|---|---|---|
| `__init__.py` | 766 B | **Package entry point** — exports public API (`Orchestrator`, `AGENT_REGISTRY`, `WORKFLOW_REGISTRY`, `TOOL_REGISTRY`, models) |
| `core.py` | 5.9 KB | **Main orchestrator class** — submit/resume workflows |
| `agents.py` | 10.3 KB | Agent definitions + Claude Code executor integration (`AGENT_REGISTRY`) |
| `workflows.py` | 6.6 KB | Static workflow definitions (`WORKFLOW_REGISTRY`) keyed by request type |
| `tools.py` | 6.4 KB | Callable tools registry (`TOOL_REGISTRY`) invoked by agents |
| `models.py` | 3.4 KB | Domain types: `Step`, `Workflow`, `StepStatus`, `WorkflowStatus` |
| `runner.py` | 2.8 KB | Step/workflow execution loop |
| `checkpoint.py` | 1.9 KB | Workflow state persistence / resume support |

### Likely Entry Points
- **Programmatic API:** `Orchestrator` class imported from package root (`from agent_orchestrator import Orchestrator`).
- **Execution driver:** `runner.py` (workflow step runner).
- No `__main__.py`, no CLI entry, no script shebang detected — this is a **library/package**, not a standalone app.

### Config / Build Files
- **None present.** No `pyproject.toml`, `setup.py`, `requirements.txt`, `README.md`, `.env`, `Dockerfile`, or CI config in the scanned directory.
- Only Python source files + a `__pycache__/` directory.

### Architecture Signal
The naming (`AGENT_REGISTRY`, `WORKFLOW_REGISTRY`, `TOOL_REGISTRY`, `checkpoint.py`, `runner.py`) indicates a **registry-driven agent orchestration MVP** with checkpoint/resume semantics — likely a workflow engine wrapping Claude Code executors.

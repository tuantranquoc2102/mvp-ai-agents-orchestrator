# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Quality & Risk Assessment — `agent_orchestrator`

## HIGH

1. **No tests, no test infrastructure** (`tests/`, `pytest.ini`, `pyproject.toml` all absent). The `executor` hook is explicitly designed for test-injection, yet none exist. For a state-machine engine with retry, checkpointing, and resume semantics, this is the single biggest risk: every refactor flies blind. `runner.py:71` swallows all exceptions — there is no way to know which failure modes are covered.

2. **Subprocess input not size-bounded** (`agents.py:263-273`). `user_prompt` is piped via stdin with no upper cap; `_truncate_for_prompt` caps each *value* at 6 000 chars but the final `inputs` dict can contain many such values. A large `workflow.context` payload could hang the CLI or exceed the model context, surfacing as a generic `RuntimeError` after the 300 s timeout.

3. **Tool kwargs forwarded verbatim from `step.inputs`** (`runner.py:65`). After `_resolve_inputs`, `step.inputs` contains prior-step *outputs* (dicts). Every real tool handler (`_read_doc(path, …)`, `_write_doc(path, content, …)`) expects scalar kwargs — the `**_` swallow hides the bug but means tools effectively run with their defaults. `_read_code` only works because `analyze_codebase.py` injects `path` separately. **This will silently produce empty/wrong tool outputs for most workflows.**

## MEDIUM

4. **Checkpoint file write is `.tmp` + `os.replace`** (`checkpoint.py:38-41`) — fine for crash-safety on the same FS, but no `fsync` and no locking. Two `Orchestrator` instances on the same store will clobber each other; resume after power loss may see an empty file.

5. **`run_step` `time.sleep`** (`runner.py:76`) blocks the entire orchestrator. Combine with the 300 s subprocess timeout — a single failing step can stall the process for minutes. No cancellation hook.

6. **`Exception as exc  # noqa: BLE001`** in `_read_code` (`tools.py:117`) and the runner mask real bugs (PermissionError, OSError, decoding) as benign payloads/retries. At minimum, catch concrete types or log the traceback.

7. **`assistant` agent has `ALL_TOOLS` (`*`)** (`agents.py:173`) — defeats the least-privilege model the rest of the registry carefully enforces.

## LOW

8. **`on_attempt: callable` lowercase** (`runner.py:28`) — should be `Callable[[Step], None] | None`. The `# type: ignore` papers over a real type error.
9. **`_now()` duplicated** in `models.py` and `runner.py`.
10. **No `pyproject.toml`/version pin** — fine for stdlib-only MVP, blocks packaging.
11. **`from_dict` defaults `created_at=_now()` at deserialization** (`models.py:108-109`) — quietly rewrites timestamps if the field is missing instead of failing loudly.
12. **Mock tool handlers return fake "success" payloads** (`_run_tests`: `passed: 12, failed: 0`). Risk of being mistaken for a real run in logs.

**Top three to fix before any further work:** #1 (add tests around `runner.run_step` and `Orchestrator.resume`), #3 (separate tool-kwargs from step-inputs in the data model), #7 (drop `ALL_TOOLS` from `assistant` or gate it behind an explicit opt-in).

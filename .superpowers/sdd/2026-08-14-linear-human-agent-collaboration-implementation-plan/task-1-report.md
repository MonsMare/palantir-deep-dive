# Task 1 implementation report

## Fix round 3

- Worktree: `.worktrees/linear-task-1`
- Branch: `codex/linear-task-1`
- Base: `dadc13e`
- Scope: close the independent-review findings C1, C2, I1, I2, and M1 while preserving trusted run/version/fix-round derivation, human-only approval and production actions, immutable transition rules, audit fields, and stale active runs after contract changes.

### Changes

- Removed importable authorization sentinels. `TaskEvent` can only be issued by the lifecycle factory, and registry commit revalidates the bound principal, audit fields, run/version/state, derived destination, and fix-round.
- Removed public registry transition/failure/staleness mutation methods. Accepted events and state replacement are committed through one `RLock`-protected path, so a concurrent stale snapshot cannot append an event without the matching state change.
- Rejected active runs whose contract-version snapshot differs from the `TaskRecord` version at model validation time.
- Resolved actor authority only from the trusted resolver binding; actor names are not interpreted as authority. Added a pure `TaskLifecycle.derive` API separate from governed `apply`.

### Verification

- TDD RED before implementation: `pytest tests/task -q` — 36 passed, 7 failed, covering the newly added bypass, concurrency, version, resolver-name, and derive cases.
- GREEN: `pytest tests/task -q` — 43 passed.
- Governance regression: `pytest tests/unit/test_action_broker.py tests/unit/test_tool_gateway.py tests/gates/test_gate_engine.py tests/task -q` — 113 passed.
- Compile check: `python -m compileall -q src/aifde/task tests/task` — passed.
- Whitespace check: `git diff --check` — passed.

### Concerns

- Verification covers the requested Task/governance scope; the full repository test suite was not run in this round.
- The authorization boundary is an in-process Python boundary; persistence adapters must retain the event binding/audit revalidation contract when deserializing events.

## Fix round 4

- Worktree: `.worktrees/linear-task-1`
- Branch: `codex/linear-task-1`
- Base: `fa09627`
- Scope: fix the review finding that successful lifecycle applies retained `_pending_events` bindings, causing unbounded memory growth over long-running applies.

### Changes

- Moved pending-event binding lookup inside the commit `try` block and unconditionally removed the binding by event identity in `finally`, covering successful commits and all validation, authorization, state-conflict, and unexpected exceptions.
- Added `test_successful_apply_clears_pending_event_after_commit`, which verifies `registry._pending_events` is empty after a successful `apply` while the accepted audit event remains in `registry.events`.
- Preserved the existing audit append/event-id registration and all trusted-principal, run identity, contract version, state, transition, and fix-round security checks.

### Verification

- TDD RED: `pytest tests/task/test_task_lifecycle.py::test_successful_apply_clears_pending_event_after_commit -q` — failed on the base cleanup condition with `len(registry._pending_events) == 1`.
- GREEN: the same focused test — 1 passed.
- Task tests: `pytest tests/task -q` — 44 passed.
- Governance regression: `pytest tests/unit/test_action_broker.py tests/unit/test_tool_gateway.py tests/gates/test_gate_engine.py tests/task -q` — 114 passed.
- Compile check: `python -m compileall -q src/aifde/task tests/task` — passed.
- Whitespace check: `git diff --check` — passed (exit code 0; only Git's LF/CRLF conversion warnings were emitted).

### Concerns

- Full repository `pytest` — 352 passed, 14 failed, 13 errors. The failures/errors are outside this round's lifecycle files, in builder/domain/e2e/platform/runtime paths; the requested Task and governance regressions remain green.

# Task 6 Report: software-delivery vertical slice

## Status

Implementation is complete on branch `codex/shipyard-workbench-phase-0`.

- Implementation commit: `1c7900f feat: prove Shipyard Workbench software delivery slice`
- Report commit: the commit containing this report
- `src/software_delivery_demo/app.py` was intentionally not modified. The existing demo API behavior is preserved; the new bootstrap is a separate builder-side adapter around the existing sandbox pipeline.

## Delivered behavior

1. `src/aifde/shipyard/bootstrap.py`
   - Creates the deterministic `software-delivery-demo` Workspace through `ShipyardApplicationService`.
   - Reads the six checked-in project assets as typed `Artifact` records: `ProjectCharter`, `DecisionContract`, `OntologyModel`, `DataProduct`, `FeatureCatalog` and `ModelPolicy`.
   - Preserves source references, raw source SHA-256, content hash, version, dependency lineage, validation result and `producer="shipyard-seed"`.
   - Runs the local deterministic `software_delivery_demo.pipeline` as a sandbox adapter and maps required gates to immutable `GateReviewSnapshot` values containing validator version, exact Artifact hashes, evidence references and stale state.
   - Returns snapshots without persisting them; callers must use the system gate-runner through the Application Service to record them.
   - If an optional demo evaluation dependency is unavailable, the adapter produces blocked snapshots rather than claiming that evaluation passed.
2. `scripts/shipyard_seed.py`
   - Accepts `--database PATH --owner USER`.
   - Creates missing database parent directories.
   - Initializes a local SQLite Workbench with Workspace, Decision Case, six Artifacts and initial Gate Reviews.
   - Does not connect to Linear or customer systems and does not execute production Actions.
3. Integration and E2E tests
   - Prove release blocking before required gates.
   - Prove deterministic Gate snapshots and exact Artifact hash binding.
   - Prove the Workbench sequence: Workspace → Decision Case → snapshot → Agent Proposal → human return → passed Gate Reviews → Release Candidate → audit and manifest digest.
4. Documentation
   - Marks Phase 0 as Workbench review/release eligibility, not a customer runtime, full ML Evaluation Lab, production connector, Docker deployment or Linear integration.

## Verification

### TDD RED

Before production implementation, ran:

```powershell
pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q
```

Expected RED was observed: both modules failed collection with
`ModuleNotFoundError: No module named 'aifde.shipyard.bootstrap'`.

### GREEN and regression

```text
pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q
3 passed

pytest tests/shipyard tests/api tests/gates -q
110 passed

python -m py_compile src/aifde/shipyard/bootstrap.py scripts/shipyard_seed.py tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py
passed

git diff --check
passed (only Git's normal LF/CRLF conversion warnings appeared during staging)

cd workbench; npm test -- --run; npm run build
13 frontend tests passed; Vite production build passed
```

The CLI was run with the requested interface against a fresh nested temporary
path:

```powershell
python scripts/shipyard_seed.py --database C:\Users\meta\AppData\Local\Temp\aifde-task6-seed-final\nested\shipyard.db --owner alice
```

It exited `0`, created the parent directories and database, and reported six
Artifacts plus two Gate Reviews. The active `python` executable in this
worktree does not include Polars, so the safe fallback marked both reviews
`blocked`; no release was incorrectly allowed. The normal Anaconda/pytest
environment has the demo dependencies and exercises the real sandbox pipeline
in the focused tests.

The broader existing API/Shipyard/E2E command produced `75 passed, 2 failed`:

```powershell
pytest tests/shipyard tests/api tests/e2e -q
```

Both failures are pre-existing baseline failures in
`tests/e2e/test_production_two_domain_flow.py`: the starting clean branch
lacks the `builder_source_snapshots` SQLite table and raises
`sqlite3.OperationalError: no such table: builder_source_snapshots`. Task 6
does not touch the builder persistence path or copy that unrelated main-workspace
change.

## Deferred minor items

- The seed command is intentionally a fresh-database command. Re-running it on
  the same database fails on the append-only Workspace revision instead of
  silently overwriting records; a resumable/idempotent seed command belongs in
  a later operational task.
- The three-argument artifact seed interface resolves the checked-in project
  assets from the repository package root. A future packaged Shipyard may
  replace this with an explicit source resolver/object-store adapter.
- The full Evaluation Lab, customer connectors, Docker deployment and
  customer-side runtime remain follow-up plans; Phase 0 only proves the review
  and release-eligibility boundary.
- An earlier Task 3 minor remains unchanged: an empty `gate_run_ids` request
  reports `release requires at least one Gate Review` before the required-gate
  message. The new slice asserts the governed `ReleaseBlockedError` behavior
  without changing that existing service contract.

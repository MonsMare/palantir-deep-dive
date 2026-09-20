# Task 1 Report: Evidence Domain Contracts and Source Registry

## Status

Completed. Implemented the immutable evidence-domain contracts and in-memory source registry within the task scope.

## TDD evidence

### RED

Command:

```text
pytest tests/builder/test_source_registry.py -q
```

Result:

```text
ERROR collecting tests/builder/test_source_registry.py
ModuleNotFoundError: No module named 'aifde.builder'
1 error during collection
```

This confirmed the focused tests failed because the requested builder package and contracts did not yet exist.

### GREEN

Command:

```text
pytest tests/builder/test_source_registry.py -q
```

Result:

```text
......                                                                   [100%]
6 passed in 0.12s
```

The final test assertion uses Pydantic v2's `ValidationError` for frozen-instance assignment.

## Implemented files

- `src/aifde/builder/__init__.py`
  - Exports the builder contracts and registry.
- `src/aifde/builder/contracts.py`
  - Adds frozen Pydantic `SourceAsset`, `SourceSnapshot`, and `EvidenceFragment` models.
  - Provides registration/capture/slicing constructors.
  - Normalizes bytes before SHA-256 hashing.
  - Rejects naive datetimes and blank identities/locators.
  - Retains original and normalized evidence text plus source and fragment hashes.
- `src/aifde/builder/sources.py`
  - Adds an append-only, in-memory `SourceRegistry`.
  - Rejects changed content for an existing `(source_asset_id, version)`.
  - Supports defensive retrieval and fragment listing.
- `tests/builder/test_source_registry.py`
  - Covers stable hashes and locators, append-only behavior, idempotent capture, validation, defensive copies, and overlapping fixtures.
- `tests/builder/fixtures/supplier_purchase_orders.json`
  - Contains purchase orders and promised dates.
- `tests/builder/fixtures/supplier_notes.md`
  - Contains a display-name variant for the same supplier and a changed promised date.

## Risks and limitations

- The registry is in-memory only; persistence and cross-process concurrency are outside Task 1.
- Snapshot and fragment identifiers are deterministic for the relevant source/content identity, but there is no external UUID allocation or migration layer.
- Fixture overlap is intentionally represented by text and source locations; semantic entity resolution is deferred to later tasks.
- The full repository regression run was started during an interrupted turn but was not used as the completion gate for this request; the verified completion gate is the focused six-test suite above.


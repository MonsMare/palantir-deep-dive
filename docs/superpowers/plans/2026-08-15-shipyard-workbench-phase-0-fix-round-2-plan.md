# Shipyard Workbench Task 6 Fix Round 2 Implementation Plan

> **For agentic workers:** Execute this plan inline with TDD checkpoints; no subagent is required for this focused fix round.

**Goal:** Make the software-delivery Gate evaluator consume and semantically validate all six registered Artifacts, and make evaluator outcomes tamper-evident so blocked results cannot become release-eligible passed reviews.

**Architecture:** Add a deterministic Artifact semantic evaluator beside the existing provenance builder. It uses a fixed Artifact-ID-to-asset/kind contract, validates registered canonical content against the expected source asset and type-specific structure, and produces evaluator evidence/stage states. The existing sandbox pipeline remains an additional check only. Add a deterministic outcome attestation over the complete Gate outcome payload; the Application Service accepts a complete passed review only when its attestation matches the governed evaluator output for the same input.

**Tech Stack:** Python, Pydantic contracts, SQLiteRegistry/ShipyardApplicationService, PyYAML, Turtle text validation, deterministic SHA-256 digests, pytest, existing Vite/Vitest Workbench.

## Global Constraints

- AI-FDE is the Shipyard builder/evaluator, not a customer production runtime.
- All bootstrap/seed persistence goes through ShipyardApplicationService; no direct Registry writes from bootstrap.
- No Linear, customer connector, external service, or production Action.
- Keep Task 1–5 APIs compatible; old GateReview shapes remain writable but cannot obtain release eligibility.
- Only the bound system identity with the `gate-runner` role may record Gate Reviews.
- M-1 seed atomicity and M-2 sandbox side effects remain deferred.

---

### Task 1: Add failing semantic/mapping/evaluator regression tests

**Files:**
- Modify: `tests/shipyard/test_software_delivery_slice.py`
- Modify: `tests/e2e/test_shipyard_workbench_flow.py` only if the original evaluator flow needs an assertion update

**Interfaces:**
- Consumes the existing `seed_software_delivery_*`, `run_workbench_gate_snapshot`, `GateReviewSnapshot` and Service APIs.
- Produces tests proving fixed source mapping, semantic invalidity, all-six input participation, and original passing snapshot behavior.

- [ ] **Step 1: Add fixed mapping failure test**

Register the `ontology-model` Artifact with a valid `config/project.yaml` envelope and matching hash/evidence metadata, then run the snapshot. Assert every review is `blocked`, `stale`, and contains an expected-source mapping violation.

- [ ] **Step 2: Add semantic content failure test**

Register an `ontology-model` whose source envelope points to `ontology/domain.ttl` but whose Turtle content is structurally invalid for the required ontology asset. Assert the snapshot is `blocked/stale` and records a semantic violation before release.

- [ ] **Step 3: Add evaluator participation assertion**

On the normal seeded snapshot, assert the evidence contains one deterministic evaluator digest/reference for each of the six Artifact IDs and that the evaluator stage states cover all six IDs.

- [ ] **Step 4: Add blocked-outcome tamper tests**

Use a governed blocked snapshot fixture, then create copies changing `status`, `stale`, `violations`, or `gate_run_id`. Assert `record_gate_review` rejects each complete-provenance tamper. Keep the original snapshot unmodified.

- [ ] **Step 5: Run the new tests before production changes**

Run:

```powershell
pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q
```

Expected: the new mapping/semantic/attestation assertions fail against the current implementation for the intended reasons, while unrelated existing assertions identify any test setup mistake.

---

### Task 2: Implement fixed Artifact mapping and deterministic semantic evaluator

**Files:**
- Modify: `src/aifde/shipyard/provenance.py`
- Modify: `src/aifde/shipyard/bootstrap.py`
- Modify: `src/aifde/shipyard/contracts.py` only if a typed evaluator result needs a public contract

**Interfaces:**
- `SOFTWARE_DELIVERY_ARTIFACT_SPECS: Mapping[str, tuple[str, str]]` maps every fixed Artifact ID to `(relative_source_path, expected_kind)`.
- `evaluate_software_delivery_artifacts(artifacts, source_root) -> ArtifactEvaluation` returns deterministic per-Artifact digests, evidence refs, stage states, violations, and an overall blocked flag.
- `build_artifact_input_snapshot` uses the fixed mapping rather than Artifact-declared path metadata as authority.

- [ ] **Step 1: Implement the fixed mapping**

Map project charter to `config/project.yaml`, decision contract to `decisions/problem.yaml`, ontology model to `ontology/domain.ttl`, data product to `data_products/contracts.yaml`, feature catalog to `features/definitions.yaml`, and model policy to `models/model_policy.yaml`, with the exact seed kinds already used by `_AssetSpec`.

- [ ] **Step 2: Implement canonical source/content/type checks**

For each required ID, require the registered Artifact kind and expected path. Read the expected file, compute raw SHA and canonical content hash, compare the registered Artifact content envelope and declared evidence, and validate type-specific structure: YAML assets must parse to a non-empty mapping; ontology Turtle must be non-empty and include RDF/Turtle structure plus the project ontology namespace; all six must have the expected envelope and non-empty document.

- [ ] **Step 3: Produce per-Artifact evaluator evidence**

For every Artifact, compute a deterministic digest over ID, kind, version, canonical content, source path/SHA and semantic result. Add a stable evaluator evidence reference containing that digest and stage state. Missing, duplicate, unmapped, semantic-invalid, or unconsumed inputs become violations and block evaluation.

- [ ] **Step 4: Make snapshot evaluation consume the evaluator result first**

Run `evaluate_software_delivery_artifacts` before the sandbox pipeline. If it blocks, do not use a passing pipeline result; return blocked Gate snapshots with evaluator violations/evidence. If it passes, run the existing sandbox pipeline only as an extra check and combine its stage states/violations without removing evaluator evidence.

- [ ] **Step 5: Run semantic tests green**

Run the focused test module and confirm mapping, semantic invalidity, participation, and normal seeded snapshots behave as specified.

---

### Task 3: Add outcome attestation and Service verification

**Files:**
- Modify: `src/aifde/shipyard/contracts.py`
- Modify: `src/aifde/shipyard/bootstrap.py`
- Modify: `src/aifde/shipyard/service.py`
- Modify: `src/aifde/api/shipyard_routes.py`
- Modify: `workbench/src/types.ts`

**Interfaces:**
- `GateReviewSnapshot.outcome_attestation: str` is an optional backward-compatible SHA-256 digest; complete evaluator reviews must populate it.
- `build_gate_outcome_attestation(...) -> str` hashes gate ID, run ID, status, stale, violations, Artifact/input/source hashes, validator/definition fingerprint, evidence refs, and stage states in canonical order.
- Service verifies the attestation against the immutable evaluator output expected for the current run before storing a complete passed review or releasing a Candidate.

- [ ] **Step 1: Add attestation fields and canonical digest helper**

Add the optional validated SHA-256 field to the contract/API/frontend types and implement one canonical payload helper. Keep old records parseable with an empty default.

- [ ] **Step 2: Attach attestation to evaluator-produced snapshots**

After the evaluator and sandbox stage states are finalized, compute the attestation for each Gate Review. The digest must include the final status and violations, so changing blocked to passed or clearing violations changes the expected digest.

- [ ] **Step 3: Verify complete reviews in Service**

For a complete-provenance review, recompute the expected outcome attestation from the governed evaluator result and reject any mismatch before persistence. Legacy incomplete reviews may still be recorded but are not release-eligible.

- [ ] **Step 4: Add blocked-to-passed regression coverage**

Assert `model_copy` changes to status, stale, violations, and run ID fail at record or release, while the original deterministic passing snapshot records and creates a Candidate.

- [ ] **Step 5: Run Shipyard/API/Gates tests green**

Run `pytest tests/shipyard tests/api tests/gates -q` and fix only regressions caused by the new optional contract fields or trusted evaluator boundary.

---

### Task 4: Documentation, full verification, and commits

**Files:**
- Modify: `docs/production-ai-fde-acceptance.md`
- Modify: `docs/README.md`
- Create: `.superpowers/sdd/2026-08-15-shipyard-workbench-phase-0/task-6-fix-round-2-report.md`

- [ ] **Step 1: Document evaluator/attestation boundary**

State that six registered Artifact contents are semantic evaluator inputs, the sandbox pipeline is supplementary, and outcome attestation prevents caller outcome rewrites. Preserve the customer-runtime/production-connector/Linear exclusions.

- [ ] **Step 2: Run final verification**

Run focused tests, `pytest tests/shipyard tests/api tests/gates tests/e2e -q`, frontend tests/build, `py_compile`, `git diff --check`, and fresh nested CLI seed. Record the pre-existing two `builder_source_snapshots` failures and deferred M-1/M-2.

- [ ] **Step 3: Review and commit implementation**

Use `git status`, inspect the staged diff, and commit only Task 6 fix-round-2 implementation/tests/docs changes.

- [ ] **Step 4: Commit the report separately**

Force-add the ignored report path if needed, commit it separately, and verify the final worktree is clean.

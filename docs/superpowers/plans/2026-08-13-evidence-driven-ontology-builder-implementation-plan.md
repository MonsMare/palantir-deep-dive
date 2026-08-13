# Evidence-Driven Ontology Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the next AI-FDE stage that turns messy enterprise source material into traceable evidence, semantic candidates, executable mappings, a validated business Ontology candidate, and a gated release package using deterministic simulated supplier-delay data.

**Architecture:** Add an isolated `aifde.builder` package on top of the verified AI-FDE domain, registry, RDF, and Gate Engine foundations. The Builder is append-only at the source/evidence boundary, separates immutable evidence from mutable candidates, and compiles candidates into a canonical data product plus RDFS/SHACL-compatible ontology artifacts. Candidate generation is deterministic in the demo but exposed through a provider protocol so an LLM can later propose candidates without receiving publish or write privileges.

**Tech Stack:** Python 3.11+, Pydantic v2, Polars, RDFLib, pySHACL, pytest, JSON/CSV/Turtle fixtures, existing `aifde.gates.GateEngine`.

## Global Constraints

- Chat text is not the system of record; every semantic candidate and release artifact is typed and versioned.
- Source snapshots and evidence fragments are immutable and must retain content hash, locator, source version, observed time, available time, and extraction version.
- AI or heuristic extraction may propose facts, definitions, rules, assumptions, and mappings, but it cannot silently convert an unverified proposal into a released business fact.
- Entity resolution must preserve match score, threshold, algorithm version, fields used, conflict references, and reviewer status.
- A released mapping must be executable against the supplied fixture and must produce a canonical product with stable schema, identity keys, temporal columns, and provenance links.
- A released ontology candidate must include classes, properties, relationships, states/events, identity keys, temporal semantics, access-policy bindings, evidence references, and validation artifacts.
- Hard failures block release; unresolved high-impact conflicts and missing evidence cannot be waived by the Builder itself.
- The simulated data must include overlapping source documents, source delays, conflicting supplier names, and a supplier delivery outcome that supports a meaningful delay-risk feature later.
- Every new production function is introduced through a failing test and then a minimal implementation.

---

## Task 1: Evidence domain contracts and source registry

**Files:**
- Create: `src/aifde/builder/__init__.py`
- Create: `src/aifde/builder/contracts.py`
- Create: `src/aifde/builder/sources.py`
- Create: `tests/builder/test_source_registry.py`
- Create: `tests/builder/fixtures/supplier_purchase_orders.json`
- Create: `tests/builder/fixtures/supplier_notes.md`

**Interfaces:**
- `SourceAsset.register(source_asset_id, uri, source_type, owner, authority_level, classification, access_policy_id, schema_fingerprint, metadata) -> SourceAsset`
- `SourceSnapshot.capture(source_asset, version, content, observed_at, available_at, extraction_version) -> SourceSnapshot`
- `EvidenceFragment.from_snapshot(snapshot, locator, content, normalized_content, extraction_method, event_time, confidence) -> EvidenceFragment`
- `SourceRegistry.register(asset) -> SourceAsset`
- `SourceRegistry.capture(asset_id, version, content, observed_at, available_at, extraction_version) -> SourceSnapshot`
- `SourceRegistry.slice(snapshot_id, locator, content, normalized_content=None, extraction_method="deterministic-text", event_time=None, confidence=1.0) -> EvidenceFragment`
- `SourceRegistry.get_snapshot(snapshot_id) -> SourceSnapshot`
- `SourceRegistry.get_fragment(fragment_id) -> EvidenceFragment`
- `SourceRegistry.list_fragments(snapshot_id=None) -> list[EvidenceFragment]`

- [ ] **Step 1: Write failing tests for immutable source and evidence contracts**

```python
def test_snapshot_hash_and_fragment_locator_are_stable(registry):
    asset = registry.register(SourceAsset.register(
        "erp-purchase-orders", "fixture://purchase-orders.json", "json",
        "procurement", 5, "internal", "policy:procurement", "schema-v1", {}
    ))
    snapshot = registry.capture(
        asset.source_asset_id, "2026-08-13", b'{"po_id":"PO-001"}',
        observed_at=dt(2026, 8, 13, 9), available_at=dt(2026, 8, 13, 10),
        extraction_version="raw-v1",
    )
    fragment = registry.slice(snapshot.snapshot_id, "$.orders[0]", '{"po_id":"PO-001"}')
    assert snapshot.content_hash == fragment.source_content_hash
    assert fragment.locator == "$.orders[0]"
    assert fragment.evidence_id.startswith("evidence:")


def test_source_snapshot_is_append_only(registry):
    asset = registry.register(make_asset())
    first = registry.capture(asset.source_asset_id, "v1", b"one", dt(2026, 8, 13, 9), dt(2026, 8, 13, 9), "raw-v1")
    with pytest.raises(ValueError, match="immutable"):
        registry.capture(asset.source_asset_id, "v1", b"changed", dt(2026, 8, 13, 9), dt(2026, 8, 13, 9), "raw-v1")
    assert registry.get_snapshot(first.snapshot_id).content_hash == sha256(b"one").hexdigest()
```

- [ ] **Step 2: Run the focused tests and verify the expected missing-module failure**

Run: `pytest tests/builder/test_source_registry.py -q`

Expected: collection fails because `aifde.builder` does not exist.

- [ ] **Step 3: Implement the minimal immutable contracts and in-memory registry**

Use Pydantic frozen models for source snapshots and evidence. Canonicalize bytes before hashing, reject naive datetimes, reject blank IDs/locators, and reject duplicate `(source_asset_id, version)` captures with a different content hash. Store original and normalized evidence text together; `list_fragments` must return defensive copies.

- [ ] **Step 4: Add the overlapping supplier fixtures and test deterministic capture**

The JSON fixture must contain purchase orders and promised dates. The Markdown fixture must repeat the same supplier under a display-name variant and contain a note that a promised date changed. Tests must show both fragments point to their original source locations.

- [ ] **Step 5: Run focused and baseline tests, then commit**

Run: `pytest tests/builder/test_source_registry.py -q`

Commit: `feat: add evidence-driven source registry`

---

## Task 2: Candidate extraction, entity resolution, and semantic assertions

**Files:**
- Create: `src/aifde/builder/semantic.py`
- Create: `tests/builder/test_semantic_candidates.py`

**Interfaces:**
- `CandidateProvider.propose(fragments: list[EvidenceFragment], context: BuilderContext) -> CandidateProposal`
- `BuilderContext` carries `project_id`, `domain`, `ontology_version`, and `known_terms`.
- `CandidateProposal` contains `terms`, `entities`, `assertions`, `mappings`, `warnings`, `evidence_refs`, a proposal version, builder-context digest, and release eligibility.
- `DeterministicCandidateProvider` extracts supplier, purchase-order, promised-date, actual-delivery-date, and delay-note candidates from the fixtures.
- `EntityResolver.resolve(candidates: list[EntityCandidate], strategy_version: str) -> list[EntityMatch]`
- `SemanticCandidateBuilder.build(fragments, context) -> CandidateProposal`

- [x] **Step 1: Write failing tests for evidence-bound candidates and conservative matching**

```python
def test_candidate_proposal_keeps_fact_definition_and_assumption_distinct(proposal):
    assert {item.assertion_type for item in proposal.assertions} == {"fact", "definition", "assumption", "inference"}
    assert all(item.evidence_refs for item in proposal.assertions if item.assertion_type == "fact")


def test_supplier_alias_is_probable_match_but_conflict_stays_open(proposal):
    match = next(item for item in proposal.entity_matches if item.candidate_id == "supplier:acme-east")
    assert match.canonical_entity_id == "supplier:acme"
    assert match.score >= match.threshold
    assert match.status == "probable_match"
    assert match.conflict_refs


def test_provider_never_promotes_unanchored_inference(proposal):
    for assertion in proposal.assertions:
        if assertion.assertion_type in {"fact", "definition", "rule"}:
            assert assertion.evidence_refs
```

- [x] **Step 2: Run the focused tests and verify they fail for the absent semantic builder**

Run: `pytest tests/builder/test_semantic_candidates.py -q`

Expected: collection or import failure because the semantic module is absent.

- [x] **Step 3: Implement deterministic proposal extraction and pluggable provider protocol**

Extract JSON paths and Markdown line ranges into evidence references. Use a typed assertion `fact | definition | rule | assumption | inference`; facts require direct evidence, definitions require a reviewer owner, rules require executable expression text, and assumptions remain unreleased. Do not use a free-form LLM response as an authoritative value.

- [x] **Step 4: Implement conservative entity resolution**

Use exact external IDs first, then normalized names, then an explicit alias table. For fuzzy/variant matches, emit a score, threshold, matching fields, algorithm version, and conflict refs. High-impact supplier merges remain `probable_match` until a reviewer confirms them.

- [x] **Step 5: Run focused tests and commit**

Run: `pytest tests/builder/test_semantic_candidates.py -q`

Commit: `feat: build evidence-bound semantic candidates`

Review repair requirements are part of the completed contract: evidence
references must semantically support assertions; only source-explicit
external keys can yield `confirmed`; proposals carry version/context
provenance; assumptions remain unreleased; and nested assertion values are
immutable.

---

## Task 3: Ontology and mapping compiler with executable product materialization

**Files:**
- Create: `src/aifde/builder/compiler.py`
- Create: `tests/builder/test_compiler.py`
- Create: `projects/supplier-delay-builder-demo/ontology/ontology.ttl`
- Create: `projects/supplier-delay-builder-demo/ontology/shapes.ttl`

**Interfaces:**
- `MappingCompiler.compile(proposal, source_registry, version) -> CompileResult`
- `MappingSpec` includes `source_field_path`, `target_product`, `target_grain`, `target_field`, `transform_expression`, `identity_rule`, `time_semantics`, `null_policy`, `lineage_refs`, and `security_policy`.
- `CompileResult` contains `ontology_candidate`, `mapping_specs`, `canonical_rows`, `provenance_rows`, `validation_report`, and `artifact_hashes`.
- `MappingCompiler.materialize(mapping_spec, snapshots) -> list[dict[str, object]]`
- `MappingCompiler.render_turtle(ontology_candidate) -> str`
- `MappingCompiler.validate(result) -> CompileValidation`

- [ ] **Step 1: Write failing tests for mapping execution, time semantics, provenance, and ontology rendering**

```python
def test_mapping_materializes_one_canonical_purchase_order_with_lineage(result):
    row = next(item for item in result.canonical_rows if item["purchase_order_id"] == "PO-001")
    assert row["supplier_id"] == "supplier:acme"
    assert row["promised_delivery_date"]
    assert row["observed_at"] <= row["available_at"]
    provenance = next(item for item in result.provenance_rows if item["target_id"] == "PO-001")
    assert provenance["evidence_refs"]


def test_compiler_rejects_future_available_time_and_invalid_grain(result):
    broken = replace(result.mapping_specs[0], target_grain="supplier")
    with pytest.raises(ValueError, match="target grain"):
        MappingCompiler().validate(replace(result, mapping_specs=[broken]))


def test_rendered_ontology_contains_classes_properties_and_shapes(result):
    assert "PurchaseOrder" in result.ontology_turtle
    assert "promisedDeliveryDate" in result.ontology_turtle
    assert "shapes" in result.artifact_hashes
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `pytest tests/builder/test_compiler.py -q`

Expected: import failure because the compiler is absent.

- [ ] **Step 3: Implement mapping contracts and deterministic materialization**

Compile source JSON/Markdown candidates to a canonical `purchase_order` product at purchase-order grain. Keep `event_time`, `observed_at`, and `available_at` separate. Attach evidence references and source locations to every canonical row. Reject mappings whose target grain does not match the compiled product or whose source field path cannot be resolved.

- [ ] **Step 4: Render the Ontology candidate and SHACL shapes**

Generate classes for `Supplier`, `PurchaseOrder`, `DeliveryEvent`, and `DeliveryException`; properties for identity, promised/actual delivery dates, and delay state; and a relationship from purchase order to supplier. Generate shapes for required identity and temporal fields. The compiler writes candidate artifacts, not released facts.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/builder/test_compiler.py -q`

Commit: `feat: compile ontology and executable mappings`

---

## Task 4: Builder run orchestration, gates, release package, and simulated scenario

**Files:**
- Create: `src/aifde/builder/flow.py`
- Create: `src/aifde/builder/gates.py`
- Create: `src/software_delivery_demo/builder_demo.py`
- Create: `tests/builder/test_builder_flow.py`
- Create: `projects/supplier-delay-builder-demo/README.md`
- Create: `projects/supplier-delay-builder-demo/fixtures/purchase_orders.json`
- Create: `projects/supplier-delay-builder-demo/fixtures/supplier_notes.md`

**Interfaces:**
- `BuilderRunConfig` contains `project_id`, `domain`, `ontology_version`, `actor_id`, `source_paths`, and `approval_actor`.
- `BuilderRunResult` contains `run_id`, `state`, `proposal`, `compile_result`, `gate_report`, `release_package`, and `blocking_reasons`.
- `EvidenceDrivenOntologyBuilder.run(config) -> BuilderRunResult`
- `BuilderGateRunner.evaluate(proposal, compile_result) -> BuilderGateReport`
- `BuilderGateRunner.release(result, approval_actor) -> OntologyReleasePackage`
- `run_supplier_delay_builder_demo(project_root) -> BuilderRunResult`

- [ ] **Step 1: Write failing end-to-end tests for release and blocking paths**

```python
def test_supplier_delay_builder_releases_traceable_ontology(project_root):
    result = run_supplier_delay_builder_demo(project_root)
    assert result.state == "released"
    assert result.release_package.ontology_version == "0.1.0"
    assert result.gate_report.all_hard_gates_passed
    assert result.compile_result.canonical_rows
    assert all(row["evidence_refs"] for row in result.compile_result.provenance_rows)


def test_unresolved_high_impact_merge_blocks_release(project_root):
    result = run_supplier_delay_builder_demo(project_root, force_supplier_conflict=True)
    assert result.state == "blocked"
    assert "entity" in " ".join(result.blocking_reasons).lower()
    assert result.release_package is None


def test_released_package_contains_rollback_and_dependency_hashes(project_root):
    result = run_supplier_delay_builder_demo(project_root)
    assert result.release_package.rollback_target is None
    assert result.release_package.dependency_versions
    assert result.release_package.mapping_artifact_hash
```

- [ ] **Step 2: Run the focused end-to-end tests and verify they fail**

Run: `pytest tests/builder/test_builder_flow.py -q`

Expected: import failure because Builder flow and demo are absent.

- [ ] **Step 3: Implement builder orchestration and deterministic gate report**

The flow is `register source -> capture snapshots -> slice evidence -> propose candidates -> resolve entities -> compile -> validate -> gate -> human approval -> release package`. Hard gates cover source/evidence integrity, semantic integrity, executable mapping, temporal safety, provenance completeness, and high-impact conflict handling. The Builder may produce a proposal and validation report but must not self-approve.

- [ ] **Step 4: Connect to the existing Gate Engine without bypassing it**

Register a `StageRun` for `ontology.builder`, use the existing validation context and transition service, and record gate results as immutable snapshots. The release helper must require an explicit approval actor and must reject a Builder actor as approver.

- [ ] **Step 5: Add the supplier-delay simulated scenario and operator README**

The fixture contains at least three purchase orders, two representations of the same supplier, one promised-date revision, an actual delivery event, and a note that is available one day after the event. The README explains how to run the demo, where evidence/provenance lives, what is released, and how the blocked conflict case differs.

- [ ] **Step 6: Run focused tests, complete full regression, and commit**

Run: `pytest tests/builder -q` and then `pytest -q`.

Commit: `feat: run gated evidence-driven ontology builder`

---

## Completion audit

- [ ] Every source snapshot and evidence fragment is immutable, hashed, located, and time-aware.
- [ ] Every released semantic fact and mapping is evidence-bound.
- [ ] Entity merges retain score, threshold, fields, algorithm version, conflict refs, and review state.
- [ ] Mapping execution produces canonical product rows and provenance rows.
- [ ] Ontology and SHACL artifacts are rendered and validated.
- [ ] Hard gate failure blocks release and the Builder cannot approve itself.
- [ ] The supplier-delay demo releases the clean case and blocks the unresolved conflict case.
- [ ] The full existing AI-FDE Builder and software-delivery demo regression remains green.

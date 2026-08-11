# AI FDE Builder Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a local/private AI FDE Builder that turns business evidence into versioned engineering artifacts and only advances artifacts through non-bypassable quality gates.

**Architecture:** Use a Python package with a SQLite-backed artifact/evidence registry, a versioned Gate Engine, a capability-based Tool Gateway, a stage orchestrator, and a FastAPI/Streamlit review surface. The first implementation uses deterministic fake agents and mock Actions; an LLM adapter is added behind the same interfaces without granting it direct state-transition or production-write privileges.

**Tech Stack:** Python 3.12, Pydantic v2, SQLite, FastAPI, Streamlit, RDFLib, pySHACL, DuckDB, Polars, pytest, httpx, OR-Tools, MLflow-compatible local model records, Git.

## Global Constraints

- Deployment is local/private and Git-first.
- Agent outputs are typed Artifacts; chat text is never the system of record.
- Every critical Claim requires Evidence references and a validation status.
- All stage transitions pass through one Gate Engine and one state-transition service.
- Builder agents cannot approve their own artifacts.
- Hard gate failures block transitions; soft waivers require an owner, reason, remediation, and expiry.
- Artifact, evidence snapshot, gate definition, validator, and policy versions invalidate stale gate results when changed.
- No model is released without a time-correct label, a baseline, a leakage check, and a replayable evaluation.
- No optimization plan is released without an objective, variables, hard constraints, feasibility evidence, and a user approval record.
- No Action executes without policy, parameter validation, idempotency, audit, and an outcome record.
- The MVP executes only mock Actions.
- Each task ends with an independently runnable test command and a focused Git commit.
- No external Jira, GitHub, ERP, or production system connector is implemented in this plan.

## File and module map

The repository currently contains research documents and no application package. The implementation creates these focused units:

    pyproject.toml
    src/aifde/domain/
      artifacts.py       typed Artifact and ChangeSet models
      evidence.py        Evidence, Claim, and snapshot models
      feedback.py        Feedback and user/system outcome models
      stages.py          stage state machine models
      gates.py           GateDefinition, GateRun, and waiver models
      actions.py         Action request and outcome models
    src/aifde/registry/
      protocol.py        repository interfaces
      sqlite.py          SQLite schema and transaction adapter
    src/aifde/gates/
      engine.py          gate evaluation and transition blocking
      validators.py      deterministic validator protocol
      definitions.py     built-in gate definitions
      meta.py            gate bypass and invalidation tests
    src/aifde/policy/
      capabilities.py    Read/Propose/Validate/Approve/Execute capabilities
      gateway.py         Tool Gateway and policy enforcement
    src/aifde/orchestration/
      contracts.py       TaskContract and StageRun inputs
      runner.py          stage orchestration
      agents.py          Builder, Challenger, and deterministic agent adapters
    src/aifde/tools/
      protocol.py        typed tool interface and ToolContext
      artifacts.py       artifact creation and diff tools
      evidence.py        evidence retrieval tools
      validation.py      schema and semantic validation tools
      actions.py         mock Action broker tool
    src/aifde/ontology/
      rdf.py             RDF/SHACL adapter
      shapes.py          built-in Shape loading
    src/aifde/api/
      app.py             FastAPI application factory
      routes.py          artifact, gate, stage, and approval routes
    src/aifde/ui/
      dashboard.py       Streamlit project cockpit
    tests/
      unit/               isolated domain and registry tests
      gates/              hard gate and bypass tests
      orchestration/     stage runner tests
      api/                HTTP contract tests
      fixtures/           evidence, artifacts, and gate fixtures

## Task 1: Create the package skeleton and domain contracts

**Files:**
- Create: pyproject.toml
- Create: src/aifde/__init__.py
- Create: src/aifde/domain/artifacts.py
- Create: src/aifde/domain/evidence.py
- Create: src/aifde/domain/feedback.py
- Create: src/aifde/domain/stages.py
- Create: src/aifde/domain/gates.py
- Create: src/aifde/domain/actions.py
- Create: tests/unit/test_domain_contracts.py

**Interfaces:**
- Artifact has artifact_id, project_id, kind, version, status, owner, content, depends_on, evidence_refs, content_hash, and metadata.
- Evidence has evidence_id, source_uri, locator, content_hash, captured_at, classification, and metadata.
- Claim has claim_id, artifact_id, claim_type, text, evidence_refs, confidence, and validation_status.
- StageState is an enum with draft, validating, challenging, domain_review, approved, release_candidate, released, remediation, blocked.
- GateResult is an enum with passed, failed, blocked, pending.
- StageRun has stage_run_id, project_id, stage_id, state, input_artifact_ids, output_artifact_ids, evidence_refs, open_questions, and blocking_reasons.
- Feedback has feedback_id, artifact_id, feedback_type, value, source, created_at, and metadata.
- ActionRequest has action_id, action_type, target_id, parameters, requested_by, idempotency_key, and approval_id.

- [ ] Step 1: Write the failing domain serialization tests.

Create tests/unit/test_domain_contracts.py with tests for required fields, enum validation, and deterministic content hashing:

~~~python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from aifde.domain.artifacts import Artifact
from aifde.domain.evidence import Claim
from aifde.domain.stages import StageState


def test_artifact_requires_identity_and_kind():
    with pytest.raises(ValidationError):
        Artifact(project_id="p1", kind="OntologyModel")


def test_artifact_hash_is_stable_for_same_content():
    first = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
    )
    second = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
    )
    assert first.content_hash == second.content_hash


def test_claim_rejects_unknown_claim_type():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1",
            artifact_id="a1",
            claim_type="guess",
            text="unsupported",
        )


def test_stage_state_has_blocked_state():
    assert StageState.BLOCKED.value == "blocked"
~~~

- [ ] Step 2: Run the focused test to verify it fails because the package does not exist.

Run: pytest tests/unit/test_domain_contracts.py -q
Expected: FAIL with an import or module-not-found error.

- [ ] Step 3: Create the minimal package metadata and Pydantic models.

Define Artifact.build so it canonicalizes JSON with sorted keys and hashes UTF-8 content. Use model validators to reject empty project_id, kind, and owner. Define Claim.claim_type as fact, inference, assumption, or unknown.

- [ ] Step 4: Run the focused test to verify it passes.

Run: pytest tests/unit/test_domain_contracts.py -q
Expected: 4 passed.

- [ ] Step 5: Commit the domain contract.

Run:
    git add pyproject.toml src/aifde/domain tests/unit/test_domain_contracts.py
    git commit -m "feat: add AI FDE domain contracts"

## Task 2: Implement immutable evidence and artifact repositories

**Files:**
- Create: src/aifde/registry/protocol.py
- Create: src/aifde/registry/sqlite.py
- Create: tests/unit/test_sqlite_registry.py
- Create: tests/fixtures/evidence.json

**Interfaces:**
- ArtifactRepository.put(artifact: Artifact) -> Artifact
- ArtifactRepository.get(project_id: str, artifact_id: str, version: str | None = None) -> Artifact
- ArtifactRepository.list_versions(project_id: str, artifact_id: str) -> list[Artifact]
- EvidenceRepository.put(evidence: Evidence, content: bytes) -> Evidence
- EvidenceRepository.get(evidence_id: str) -> Evidence
- EvidenceRepository.read_content(evidence_id: str) -> bytes
- RegistryTransaction.commit() -> None

- [ ] Step 1: Write repository tests for persistence, immutability, and content hashes.

~~~python
def test_artifact_versions_are_append_only(registry):
    first = make_artifact(version="0.1.0", content={"a": 1})
    second = make_artifact(version="0.2.0", content={"a": 2})
    registry.artifacts.put(first)
    registry.artifacts.put(second)

    versions = registry.artifacts.list_versions("p1", first.artifact_id)
    assert [item.version for item in versions] == ["0.1.0", "0.2.0"]

    with pytest.raises(ValueError, match="immutable"):
        registry.artifacts.put(first.model_copy(update={"content_hash": "tampered"}))


def test_evidence_content_hash_matches_stored_bytes(registry):
    payload = b"source evidence"
    evidence = make_evidence()
    saved = registry.evidence.put(evidence, payload)
    assert saved.content_hash == sha256(payload).hexdigest()
    assert registry.evidence.read_content(evidence.evidence_id) == payload
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/unit/test_sqlite_registry.py -q
Expected: FAIL because the repository protocol and SQLite adapter are absent.

- [ ] Step 3: Create the SQLite schema and repository adapters.

Use one SQLite database with tables for artifacts, artifact_versions, evidence, evidence_content, claims, stage_runs, gate_runs, approvals, and action_outcomes. Use explicit transactions. Never update an artifact version in place. Store JSON fields as canonical JSON text.

- [ ] Step 4: Run the tests and verify they pass.

Run: pytest tests/unit/test_sqlite_registry.py -q
Expected: all repository tests pass.

- [ ] Step 5: Add a registry fixture for later tasks and commit.

Run:
    git add src/aifde/registry tests/unit/test_sqlite_registry.py tests/fixtures/evidence.json
    git commit -m "feat: add immutable artifact and evidence registry"

## Task 3: Implement the Gate Engine and stage-transition state machine

**Files:**
- Create: src/aifde/gates/validators.py
- Create: src/aifde/gates/definitions.py
- Create: src/aifde/gates/engine.py
- Create: tests/gates/test_gate_engine.py
- Create: tests/gates/test_gate_invalidation.py

**Interfaces:**
- Validator.validate(context: ValidationContext) -> ValidationResult
- ValidationContext has stage_run_id, artifact_ids, evidence_snapshot_id, and configuration.
- ValidationResult has passed, violations, warnings, evidence_refs, validator_version, and input_hashes.
- GateEngine.evaluate(stage_run_id: str) -> GateSummary
- GateSummary has hard_failures, soft_failures, pending_approvals, and valid_until.
- GateEngine.can_transition(stage_run_id: str, target: StageState) -> TransitionDecision
- TransitionDecision has allowed, blocking_gate_ids, warnings, and reason.
- GateEngine.transition(stage_run_id: str, target: StageState, actor: str) -> StageTransition
- StageTransition has transition_id, stage_run_id, from_state, to_state, actor, gate_run_ids, and created_at.
- GateEngine.invalidate_for_artifact_change(artifact_id: str, new_hash: str) -> int

- [ ] Step 1: Write tests for hard blocking, soft warnings, and stale gate invalidation.

~~~python
def test_failed_hard_gate_blocks_transition(gate_engine, stage_run):
    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_result(gate_id="evidence.coverage", severity="hard", result="failed"),
    )
    decision = gate_engine.can_transition(stage_run.stage_run_id, StageState.APPROVED)
    assert decision.allowed is False
    assert "evidence.coverage" in decision.blocking_gate_ids


def test_soft_gate_can_be_waived_with_expiry(gate_engine, stage_run):
    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_result(gate_id="exception.coverage", severity="soft", result="failed"),
    )
    gate_engine.add_waiver(
        stage_run.stage_run_id,
        gate_id="exception.coverage",
        owner="domain-owner",
        reason="fixture has one exception case",
        expires_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert gate_engine.can_transition(
        stage_run.stage_run_id, StageState.DOMAIN_REVIEW
    ).allowed is True


def test_artifact_change_invalidates_old_gate_result(gate_engine, stage_run):
    gate_engine.register_result(stage_run.stage_run_id, passed_gate("schema"))
    assert gate_engine.invalidate_for_artifact_change("a1", "new-hash") == 1
    assert gate_engine.can_transition(
        stage_run.stage_run_id, StageState.APPROVED
    ).allowed is False
~~~

- [ ] Step 2: Run the gate tests and verify they fail.

Run: pytest tests/gates/test_gate_engine.py tests/gates/test_gate_invalidation.py -q
Expected: FAIL because GateEngine and validators are absent.

- [ ] Step 3: Implement GateDefinition, ValidationContext, GateRun persistence, and the stage transition state machine.

Register built-in gates for reality, evidence, semantic, data, executable, adversarial, business, and release governance categories. Gate severity is hard or soft. A hard failure returns allowed=False. A soft failure returns allowed=True only when a non-expired waiver exists.

- [ ] Step 4: Implement result invalidation using artifact_hash, evidence_snapshot_id, gate_definition_version, and validator_version.

A previously passed GateRun must become stale when any of those inputs changes.

- [ ] Step 5: Run the focused gate tests.

Run: pytest tests/gates/test_gate_engine.py tests/gates/test_gate_invalidation.py -q
Expected: all tests pass.

- [ ] Step 6: Commit the gate engine.

Run:
    git add src/aifde/gates tests/gates
    git commit -m "feat: enforce gated stage transitions"

## Task 4: Add capability policy and the Tool Gateway

**Files:**
- Create: src/aifde/policy/capabilities.py
- Create: src/aifde/policy/gateway.py
- Create: src/aifde/tools/protocol.py
- Create: tests/unit/test_tool_gateway.py

**Interfaces:**
- Capability is Read, Propose, Validate, Approve, or Execute.
- ToolContext has actor_id, project_id, stage_id, artifact_ids, capability, and request_id.
- ToolContext.with_capability(capability: Capability) -> ToolContext.
- Tool has tool_id, required_capabilities, allowed_stage_ids, and call(context, payload).
- ToolResult has status, artifact_ids, evidence_refs, payload, and audit_id.
- Tool.call(context: ToolContext, payload: dict) -> ToolResult.
- ToolGateway.call(tool_id: str, context: ToolContext, payload: dict) -> ToolResult.
- PolicyEngine.authorize(context: ToolContext, tool: Tool) -> PolicyDecision.
- PolicyDecision has allowed, reason, required_capability, and audit_id.

- [ ] Step 1: Write tests that prove capability enforcement.

~~~python
def test_builder_can_propose_but_cannot_execute(builder_context, gateway):
    result = gateway.call(
        "create_artifact",
        builder_context.with_capability(Capability.PROPOSE),
        {"kind": "DecisionContract"},
    )
    assert result.status == "proposed"

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            builder_context.with_capability(Capability.PROPOSE),
            {"action_type": "ReplanSprint"},
        )


def test_stage_scope_is_enforced(gateway, builder_context):
    context = builder_context.model_copy(update={"stage_id": "ontology.design"})
    with pytest.raises(PermissionError):
        gateway.call("train_model", context, {"dataset": "future-stage"})
~~~

- [ ] Step 2: Run the test and verify it fails.

Run: pytest tests/unit/test_tool_gateway.py -q
Expected: FAIL because the capability and gateway modules are absent.

- [ ] Step 3: Implement capability checks, stage allowlists, and audit records.

Default permissions:
  - Builder: Read, Propose, Validate
  - Challenger: Read, Validate
  - Deterministic Verifier: Read, Validate
  - Domain Owner: Read, Approve
  - Release Owner: Read, Approve, Execute for approved mock Actions

Reject direct database access from tools by requiring every tool invocation to receive a ToolContext and return a typed ToolResult.

- [ ] Step 4: Run the tests and verify they pass.

Run: pytest tests/unit/test_tool_gateway.py -q
Expected: all tests pass.

- [ ] Step 5: Commit the Tool Gateway.

Run:
    git add src/aifde/policy src/aifde/tools/protocol.py tests/unit/test_tool_gateway.py
    git commit -m "feat: enforce capability-based tool access"

## Task 5: Implement mock Actions and the Action Broker

**Files:**
- Create: src/aifde/tools/actions.py
- Modify: src/aifde/domain/actions.py
- Create: tests/unit/test_action_broker.py

**Interfaces:**
- ActionBroker.validate(request: ActionRequest) -> ActionValidation
- ActionBroker.execute(request: ActionRequest, actor: str) -> ActionOutcome
- ActionBroker.get_outcome(action_id: str) -> ActionOutcome
- MockActionAdapter.execute(action_type: str, target_id: str, parameters: dict) -> ExternalReceipt
- ActionValidation has allowed, missing_fields, approval_required, and policy_reason.
- ExternalReceipt has external_ref, status, retryable, and response_payload.

- [ ] Step 1: Write tests for approval, idempotency, failure, and audit.

~~~python
def test_action_requires_approval(action_broker, request):
    with pytest.raises(PermissionError, match="approval"):
        action_broker.execute(request, actor="project-manager")


def test_same_idempotency_key_returns_same_outcome(action_broker, approved_request):
    first = action_broker.execute(approved_request, actor="project-manager")
    second = action_broker.execute(approved_request, actor="project-manager")
    assert first.outcome_id == second.outcome_id


def test_mock_failure_produces_failed_outcome(action_broker, approved_request):
    failed = approved_request.with_parameters({"simulate_failure": True})
    outcome = action_broker.execute(failed, actor="project-manager")
    assert outcome.success is False
    assert outcome.retryable is True
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/unit/test_action_broker.py -q
Expected: FAIL because ActionBroker is absent.

- [ ] Step 3: Implement ActionBroker with approval lookup, idempotency key lookup, adapter dispatch, and ActionOutcome persistence.

Every outcome must include request_id, actor, action_type, target_id, parameters_hash, status, retryable, external_ref, and executed_at.

- [ ] Step 4: Run the tests and verify they pass.

Run: pytest tests/unit/test_action_broker.py -q
Expected: all tests pass.

- [ ] Step 5: Commit the Action Broker.

Run:
    git add src/aifde/domain/actions.py src/aifde/tools/actions.py tests/unit/test_action_broker.py
    git commit -m "feat: add approved idempotent mock actions"

## Task 6: Implement orchestration, TaskContract, Builder, and Challenger adapters

**Files:**
- Create: src/aifde/orchestration/contracts.py
- Create: src/aifde/orchestration/agents.py
- Create: src/aifde/orchestration/runner.py
- Create: tests/orchestration/test_stage_runner.py
- Create: tests/orchestration/test_challenger.py

**Interfaces:**
- TaskContract with task_id, objective, stage_id, allowed_evidence, required_output, forbidden_assumptions, acceptance_tests, and escalation_conditions.
- AgentContext has project_id, stage_id, evidence_snapshot_id, artifact_ids, and tool_gateway.
- AgentProposal has artifact_ids, evidence_refs, open_questions, assumptions, and warnings.
- ChallengeReport has result, findings, evidence_refs, and required_remediation.
- Agent.run(contract: TaskContract, context: AgentContext) -> AgentProposal.
- BuilderAgent.run(...) -> AgentProposal.
- ChallengerAgent.run(...) -> ChallengeReport.
- StageRunner.run(contract: TaskContract) -> StageRun.
- StageRunner.challenge(artifact_id: str) -> ChallengeReport.
- StageRunner.request_transition(stage_run_id: str, target: StageState, actor: str) -> StageTransition.

- [ ] Step 1: Write tests that require structured proposals and evidence.

~~~python
def test_builder_proposal_contains_artifact_evidence_and_open_questions(
    stage_runner, decision_contract
):
    run = stage_runner.run(decision_contract)
    assert run.output_artifact_ids
    assert run.evidence_refs
    assert run.open_questions


def test_missing_evidence_blocks_stage(stage_runner, contract_without_evidence):
    run = stage_runner.run(contract_without_evidence)
    assert run.state == StageState.BLOCKED
    assert "evidence" in run.blocking_reasons[0].lower()


def test_challenger_finds_unmapped_claim(stage_runner, artifact_with_claim):
    report = stage_runner.challenge(artifact_with_claim)
    assert report.result == "failed"
    assert report.findings[0].code == "CLAIM_WITHOUT_SUPPORT"
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/orchestration/test_stage_runner.py tests/orchestration/test_challenger.py -q
Expected: FAIL because orchestration modules are absent.

- [ ] Step 3: Implement deterministic FakeBuilder and FakeChallenger adapters first.

FakeBuilder must only propose artifacts and never mutate stage state. FakeChallenger must load raw Evidence references independently from Builder summaries and report missing support, forbidden assumptions, and missing acceptance tests.

- [ ] Step 4: Implement StageRunner.

StageRunner must:
  1. persist StageRun;
  2. validate the TaskContract;
  3. call Builder through ToolGateway;
  4. persist proposed artifacts;
  5. call Challenger;
  6. execute configured deterministic gates;
  7. leave the run in remediation or blocked on failure;
  8. use GateEngine for every transition.

- [ ] Step 5: Run the orchestration tests.

Run: pytest tests/orchestration/test_stage_runner.py tests/orchestration/test_challenger.py -q
Expected: all tests pass.

- [ ] Step 6: Commit the orchestration layer.

Run:
    git add src/aifde/orchestration tests/orchestration
    git commit -m "feat: orchestrate evidence-bound agent stages"

## Task 7: Add RDF and SHACL validation tools

**Files:**
- Create: src/aifde/ontology/rdf.py
- Create: src/aifde/ontology/shapes.py
- Create: src/aifde/tools/validation.py
- Create: tests/gates/test_shacl_validator.py
- Create: tests/fixtures/software_delivery_shapes.ttl

**Interfaces:**
- OntologyDocument has graph, data_hash, ontology_version, and source_refs.
- OntologyDocument.load(text: str) -> OntologyDocument
- OntologyDocument.serialize(format: str = "turtle") -> str
- ShaclValidator.validate(data_text: str, shapes_text: str) -> ValidationResult
- SemanticValidationTool.call(context: ToolContext, payload: dict) -> ToolResult

- [ ] Step 1: Write valid and invalid SHACL fixtures and tests.

~~~python
def test_requirement_without_owner_fails_shacl_validator():
    result = validate_fixture("requirement_missing_owner.ttl")
    assert result.passed is False
    assert "owner" in result.message


def test_valid_requirement_passes_shacl_validator():
    result = validate_fixture("requirement_valid.ttl")
    assert result.passed is True
~~~

- [ ] Step 2: Run the test and verify it fails.

Run: pytest tests/gates/test_shacl_validator.py -q
Expected: FAIL because the RDF adapter and Shape loader are absent.

- [ ] Step 3: Implement RDFLib loading and pySHACL validation.

The validator must return passed, violations, warnings, data_hash, shapes_hash, validator_version, and evidence_refs. It must not modify the input graph.

- [ ] Step 4: Register the semantic gate with GateEngine.

A failed hard SHACL result must block the Ontology stage transition.

- [ ] Step 5: Run the tests.

Run: pytest tests/gates/test_shacl_validator.py -q
Expected: all tests pass.

- [ ] Step 6: Commit the semantic validation tools.

Run:
    git add src/aifde/ontology src/aifde/tools/validation.py tests/gates/test_shacl_validator.py tests/fixtures/software_delivery_shapes.ttl
    git commit -m "feat: validate ontology artifacts with SHACL"

## Task 8: Add API routes and the FDE project cockpit

**Files:**
- Create: src/aifde/api/app.py
- Create: src/aifde/api/routes.py
- Create: src/aifde/ui/dashboard.py
- Create: tests/api/test_stage_routes.py
- Create: tests/api/test_gate_routes.py

**Interfaces:**
- StageSummary has stage_id, state, blocking_gate_ids, pending_approval_ids, and latest_run_id.
- ArtifactSummary has artifact_id, kind, version, status, content_hash, and updated_at.
- create_app(registry, gate_engine, stage_runner, action_broker) -> FastAPI
- GET /projects/{project_id}/stages -> list[StageSummary]
- GET /projects/{project_id}/artifacts -> list[ArtifactSummary]
- GET /projects/{project_id}/gates -> list[GateSummary]
- POST /projects/{project_id}/stage-runs -> StageRunResponse
- POST /stage-runs/{stage_run_id}/transitions -> StageTransitionResponse
- POST /actions -> ActionOutcomeResponse

- [ ] Step 1: Write HTTP contract tests.

~~~python
def test_project_stage_list_returns_gate_status(client):
    response = client.get("/projects/p1/stages")
    assert response.status_code == 200
    assert response.json()[0]["stage_id"] == "decision.contract"
    assert "blocking_gate_ids" in response.json()[0]


def test_transition_route_returns_409_on_hard_gate_failure(client, blocked_stage):
    response = client.post(
        f"/stage-runs/{blocked_stage.id}/transitions",
        json={"target": "approved", "actor": "builder"},
    )
    assert response.status_code == 409
    assert "blocking" in response.json()["detail"].lower()
~~~

- [ ] Step 2: Run the HTTP tests and verify they fail.

Run: pytest tests/api/test_stage_routes.py tests/api/test_gate_routes.py -q
Expected: FAIL because the API application is absent.

- [ ] Step 3: Implement the FastAPI application factory and routes.

Routes must call the same GateEngine and ActionBroker used by the CLI and StageRunner. No route may update state directly.

- [ ] Step 4: Implement a Streamlit cockpit that reads the API.

The first screen must show project, current stage, hard gate failures, pending approvals, open questions, and the latest artifact Diff. It must not expose an Execute control for non-approved Actions.

- [ ] Step 5: Run the API tests.

Run: pytest tests/api/test_stage_routes.py tests/api/test_gate_routes.py -q
Expected: all tests pass.

- [ ] Step 6: Commit the API and cockpit.

Run:
    git add src/aifde/api src/aifde/ui tests/api
    git commit -m "feat: add gated FDE project cockpit"

## Task 9: Add release packages, feedback, and end-to-end gate tests

**Files:**
- Create: src/aifde/release.py
- Create: src/aifde/feedback.py
- Create: tests/gates/test_bypass_paths.py
- Create: tests/test_end_to_end_builder.py
- Modify: docs/superpowers/specs/2026-08-11-ai-fde-builder-design.md

**Interfaces:**
- ReleasePackage has package_id, project_id, artifact_ids, artifact_hashes, gate_run_ids, approval_ids, policy_version, created_at, and rollback_manifest.
- ReleaseVerification has passed, missing_gate_runs, missing_approvals, and errors.
- RollbackResult has restored_artifact_ids, previous_release_id, and audit_id.
- ReleaseManager.build(project_id: str, artifact_ids: list[str]) -> ReleasePackage
- ReleaseManager.verify(package_id: str) -> ReleaseVerification
- ReleaseManager.rollback(package_id: str) -> RollbackResult
- FeedbackService.record(feedback: Feedback) -> Feedback
- FeedbackService.list_for_artifact(artifact_id: str) -> list[Feedback]

- [ ] Step 1: Write the bypass and end-to-end tests.

~~~python
def test_failed_gate_cannot_be_bypassed_by_api_cli_or_runner():
    for entrypoint in [api_transition, cli_transition, runner_transition]:
        with pytest.raises(TransitionBlocked):
            entrypoint(stage_run_id="blocked-run", target="approved")


def test_release_contains_artifacts_gates_approvals_and_rollback_manifest():
    package = build_demo_release()
    assert package.artifact_ids
    assert package.passed_gate_run_ids
    assert package.approval_ids
    assert package.rollback_manifest
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/gates/test_bypass_paths.py tests/test_end_to_end_builder.py -q
Expected: FAIL because release and feedback modules are absent.

- [ ] Step 3: Implement ReleaseManager and FeedbackService.

A ReleasePackage must contain project_id, artifact_ids, artifact_hashes, gate_run_ids, approval_ids, tool_versions, policy_version, created_at, and rollback_manifest. Rollback must restore the previous released artifact versions without deleting audit history.

- [ ] Step 4: Run the end-to-end tests.

Run: pytest tests/gates/test_bypass_paths.py tests/test_end_to_end_builder.py -q
Expected: all tests pass.

- [ ] Step 5: Run the full platform test suite and static checks.

Run:
    pytest -q
    python -m compileall src
Expected: all tests pass and compileall exits 0.

- [ ] Step 6: Update the platform design specification with implementation decisions and commit.

Run:
    git add src/aifde/release.py src/aifde/feedback.py tests/gates/test_bypass_paths.py tests/test_end_to_end_builder.py docs/superpowers/specs/2026-08-11-ai-fde-builder-design.md
    git commit -m "feat: add release feedback and bypass coverage"

## Plan-level acceptance checklist

- The artifact and evidence registry is append-only by version.
- A Claim without Evidence cannot pass a hard evidence gate.
- A Builder cannot approve or release its own artifact.
- A failed hard gate blocks transition through API, CLI, and orchestration.
- Artifact or validator changes invalidate old GateRuns.
- SHACL failures block Ontology transitions.
- Mock Actions require approval, are idempotent, and emit outcomes.
- The FDE cockpit displays gate state, evidence, Diff, approvals, and blockers.
- A release package contains complete provenance and rollback information.
- The full platform test suite passes before the sample project starts.

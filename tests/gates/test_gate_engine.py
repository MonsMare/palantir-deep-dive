from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.gates.engine import GateEngine, TransitionBlocked
from aifde.gates.validators import ValidationContext, ValidationResult


APPROVAL_GATES = (
    "reality.consistency",
    "evidence.coverage",
    "semantic.integrity",
    "data.quality",
    "executable.readiness",
    "adversarial.challenge",
    "business.exception_coverage",
)


@pytest.fixture
def stage_run() -> StageRun:
    return StageRun(
        stage_run_id="run-1",
        project_id="project-1",
        stage_id="decision.contract",
        state=StageState.DOMAIN_REVIEW,
        output_artifact_ids=["artifact-1"],
        evidence_refs=["snapshot-1"],
    )


@pytest.fixture
def gate_engine(stage_run: StageRun) -> GateEngine:
    engine = GateEngine()
    engine.register_stage_run(
        stage_run,
        builder_actor="builder-1",
        validation_context=validation_context(stage_run),
    )
    return engine


def validation_result(
    *,
    passed: bool,
    artifact_hash: str = "artifact-hash-1",
    evidence_snapshot_id: str = "snapshot-1",
    validator_version: str = "1.0.0",
) -> ValidationResult:
    return ValidationResult(
        passed=passed,
        violations=[] if passed else ["required validation failed"],
        warnings=[],
        evidence_refs=[evidence_snapshot_id],
        validator_version=validator_version,
        input_hashes={"artifact-1": artifact_hash},
    )


def validation_context(
    stage_run: StageRun, *, configuration: dict[str, object] | None = None
) -> ValidationContext:
    return ValidationContext(
        stage_run_id=stage_run.stage_run_id,
        artifact_ids=stage_run.input_artifact_ids + stage_run.output_artifact_ids,
        evidence_snapshot_id="snapshot-1",
        evidence_snapshot_hash="snapshot-hash-1",
        configuration=configuration or {"threshold": 0.95},
    )


def register_required_passes(
    gate_engine: GateEngine,
    stage_run: StageRun,
    *,
    configuration: dict[str, object] | None = None,
) -> None:
    context = validation_context(stage_run, configuration=configuration)
    for gate_id in APPROVAL_GATES:
        gate_engine.register_result(
            stage_run.stage_run_id,
            gate_id=gate_id,
            result=validation_result(passed=True),
            context=context,
        )


def test_failed_hard_gate_blocks_transition(gate_engine: GateEngine, stage_run: StageRun):
    """Changing a hard failure to a pass would wrongly permit approval."""
    register_required_passes(gate_engine, stage_run)
    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="evidence.coverage",
        result=validation_result(passed=False),
        context=validation_context(stage_run),
    )

    decision = gate_engine.can_transition(stage_run.stage_run_id, StageState.APPROVED)

    assert decision.allowed is False
    assert decision.blocking_gate_ids == ["evidence.coverage"]


def test_soft_gate_requires_complete_non_expired_waiver(
    gate_engine: GateEngine, stage_run: StageRun
):
    """Removing waiver validation would allow an unowned exception into review."""
    register_required_passes(gate_engine, stage_run)
    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="business.exception_coverage",
        result=validation_result(passed=False),
        context=validation_context(stage_run),
    )
    assert gate_engine.can_transition(
        stage_run.stage_run_id, StageState.APPROVED
    ).allowed is False

    with pytest.raises(ValueError, match="remediation"):
        gate_engine.add_waiver(
            stage_run.stage_run_id,
            gate_id="business.exception_coverage",
            owner="domain-owner",
            reason="fixture has one exception case",
            remediation="",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )

    waiver_expiry = datetime.now(timezone.utc) + timedelta(days=1)
    gate_engine.add_waiver(
        stage_run.stage_run_id,
        gate_id="business.exception_coverage",
        owner="domain-owner",
        reason="fixture has one exception case",
        remediation="add the missing exception case before release",
        expires_at=waiver_expiry,
    )

    summary = gate_engine.evaluate(stage_run.stage_run_id)
    decision = gate_engine.can_transition(stage_run.stage_run_id, StageState.APPROVED)

    assert decision.allowed is True
    assert summary.valid_until == waiver_expiry
    assert summary.pending_approvals == []


def test_builder_cannot_approve_own_stage(gate_engine: GateEngine, stage_run: StageRun):
    """Removing actor separation would let a builder self-approve a stage."""
    register_required_passes(gate_engine, stage_run)

    with pytest.raises(PermissionError, match="cannot approve"):
        gate_engine.transition(
            stage_run.stage_run_id, StageState.APPROVED, actor="builder-1"
        )


def test_transition_is_typed_audited_and_uses_the_only_path(
    gate_engine: GateEngine, stage_run: StageRun
):
    """Removing transition auditing would lose the gate decision provenance."""
    register_required_passes(gate_engine, stage_run)

    transition = gate_engine.transition(
        stage_run.stage_run_id, StageState.APPROVED, actor="domain-owner"
    )

    assert transition.stage_run_id == stage_run.stage_run_id
    assert transition.from_state is StageState.DOMAIN_REVIEW
    assert transition.to_state is StageState.APPROVED
    assert transition.actor == "domain-owner"
    assert len(transition.gate_run_ids) == len(APPROVAL_GATES)
    assert transition.created_at.tzinfo is not None
    assert gate_engine.get_stage_run(stage_run.stage_run_id).state is StageState.APPROVED
    with pytest.raises(TransitionBlocked, match="not allowed"):
        gate_engine.transition(
            stage_run.stage_run_id, StageState.RELEASED, actor="release-owner"
        )


def test_approval_rejects_missing_and_partial_required_gate_results(
    gate_engine: GateEngine, stage_run: StageRun
):
    """Removing target gate policy would allow absent or partial validation evidence."""
    missing = gate_engine.can_transition(stage_run.stage_run_id, StageState.APPROVED)

    assert missing.allowed is False
    assert "evidence.coverage" in missing.blocking_gate_ids
    assert "business.exception_coverage" in missing.blocking_gate_ids

    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="evidence.coverage",
        result=validation_result(passed=True),
        context=validation_context(stage_run),
    )
    partial = gate_engine.can_transition(stage_run.stage_run_id, StageState.APPROVED)

    assert partial.allowed is False
    assert "semantic.integrity" in partial.blocking_gate_ids


def test_register_result_requires_complete_stage_input_snapshot(
    gate_engine: GateEngine,
):
    """Removing snapshot coverage checks would let a gate omit a stage artifact."""
    stage_run = StageRun(
        stage_run_id="run-with-input",
        project_id="project-1",
        stage_id="decision.contract",
        state=StageState.DOMAIN_REVIEW,
        input_artifact_ids=["input-1"],
        output_artifact_ids=["artifact-1"],
        evidence_refs=["snapshot-1"],
    )
    incomplete_context = ValidationContext(
        stage_run_id=stage_run.stage_run_id,
        artifact_ids=["artifact-1"],
        evidence_snapshot_id="snapshot-1",
        evidence_snapshot_hash="snapshot-hash-1",
        configuration={"threshold": 0.95},
    )
    gate_engine.register_stage_run(
        stage_run,
        builder_actor="builder-2",
        validation_context=ValidationContext(
            stage_run_id=stage_run.stage_run_id,
            artifact_ids=["input-1", "artifact-1"],
            evidence_snapshot_id="snapshot-1",
            evidence_snapshot_hash="snapshot-hash-1",
            configuration={"threshold": 0.95},
        ),
    )

    with pytest.raises(ValueError, match="artifact_ids"):
        gate_engine.register_result(
            stage_run.stage_run_id,
            gate_id="evidence.coverage",
            result=ValidationResult(
                passed=True,
                validator_version="1.0.0",
                evidence_refs=["snapshot-1"],
                input_hashes={"artifact-1": "artifact-hash-1"},
            ),
            context=incomplete_context,
        )

    complete_context = ValidationContext(
        stage_run_id=stage_run.stage_run_id,
        artifact_ids=["input-1", "artifact-1"],
        evidence_snapshot_id="snapshot-1",
        evidence_snapshot_hash="snapshot-hash-1",
        configuration={"threshold": 0.95},
    )
    with pytest.raises(ValueError, match="input_hashes"):
        gate_engine.register_result(
            stage_run.stage_run_id,
            gate_id="evidence.coverage",
            result=ValidationResult(
                passed=True,
                validator_version="1.0.0",
                evidence_refs=["snapshot-1"],
                input_hashes={"input-1": "input-hash"},
            ),
            context=complete_context,
        )


def test_stage_registration_keeps_existing_callers_compatible_without_registered_context(
    stage_run: StageRun,
):
    """Requiring a registered context would break callers that provide context at result time."""
    engine = GateEngine()
    engine.register_stage_run(stage_run, builder_actor="builder-1")

    gate_run = engine.register_result(
        stage_run.stage_run_id,
        gate_id="evidence.coverage",
        result=validation_result(passed=True),
        context=validation_context(stage_run),
    )

    assert gate_run.configuration == {"threshold": 0.95}
    assert gate_run.evidence_snapshot_hash == "snapshot-hash-1"


def test_engine_defensively_copies_returned_gate_and_transition_records(
    gate_engine: GateEngine, stage_run: StageRun
):
    """Returning stored mutable lists or dicts would let callers corrupt audit state."""
    register_required_passes(gate_engine, stage_run)
    returned_gate_run = gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="evidence.coverage",
        result=validation_result(passed=True),
        context=validation_context(stage_run),
    )
    returned_gate_run.artifact_hashes.clear()
    returned_gate_run.configuration.clear()

    assert gate_engine.invalidate_for_artifact_change("artifact-1", "new-hash") == len(APPROVAL_GATES) + 1

    register_required_passes(gate_engine, stage_run)
    transition = gate_engine.transition(
        stage_run.stage_run_id, StageState.APPROVED, actor="domain-owner"
    )
    transition.gate_run_ids.clear()

    assert gate_engine.list_transitions(stage_run.stage_run_id)[0].gate_run_ids


def test_stage_registration_and_transition_reject_untyped_or_blank_identities(
    stage_run: StageRun,
):
    """Removing runtime type and identity checks would permit unsafe state mutation."""
    engine = GateEngine()
    with pytest.raises(ValueError, match="builder_actor"):
        engine.register_stage_run(stage_run, builder_actor=None)

    engine.register_stage_run(
        stage_run,
        builder_actor="builder-1",
        validation_context=validation_context(stage_run),
    )
    with pytest.raises(TypeError, match="StageState"):
        engine.can_transition(stage_run.stage_run_id, "approved")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="actor"):
        engine.transition(stage_run.stage_run_id, StageState.APPROVED, actor=" ")


def test_release_candidate_and_release_require_release_governance_gate(
    gate_engine: GateEngine, stage_run: StageRun
):
    """Removing release target policy would let approved work ship without release governance."""
    register_required_passes(gate_engine, stage_run)
    gate_engine.transition(stage_run.stage_run_id, StageState.APPROVED, actor="domain-owner")

    release_candidate = gate_engine.can_transition(
        stage_run.stage_run_id, StageState.RELEASE_CANDIDATE
    )

    assert release_candidate.allowed is False
    assert release_candidate.blocking_gate_ids == ["release.governance"]

    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="release.governance",
        result=validation_result(passed=True),
        context=validation_context(stage_run),
    )
    gate_engine.transition(
        stage_run.stage_run_id,
        StageState.RELEASE_CANDIDATE,
        actor="release-owner",
    )

    assert gate_engine.can_transition(stage_run.stage_run_id, StageState.RELEASED).allowed is True

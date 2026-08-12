from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.gates.engine import GateEngine, TransitionBlocked
from aifde.gates.validators import ValidationContext, ValidationResult


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
    engine.register_stage_run(stage_run, builder_actor="builder-1")
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


def test_failed_hard_gate_blocks_transition(gate_engine: GateEngine, stage_run: StageRun):
    """Changing a hard failure to a pass would wrongly permit approval."""
    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="evidence.coverage",
        result=validation_result(passed=False),
    )

    decision = gate_engine.can_transition(stage_run.stage_run_id, StageState.APPROVED)

    assert decision.allowed is False
    assert decision.blocking_gate_ids == ["evidence.coverage"]


def test_soft_gate_requires_complete_non_expired_waiver(
    gate_engine: GateEngine, stage_run: StageRun
):
    """Removing waiver validation would allow an unowned exception into review."""
    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="business.exception_coverage",
        result=validation_result(passed=False),
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
    gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="evidence.coverage",
        result=validation_result(passed=True),
    )

    with pytest.raises(PermissionError, match="cannot approve"):
        gate_engine.transition(
            stage_run.stage_run_id, StageState.APPROVED, actor="builder-1"
        )


def test_transition_is_typed_audited_and_uses_the_only_path(
    gate_engine: GateEngine, stage_run: StageRun
):
    """Removing transition auditing would lose the gate decision provenance."""
    gate_run = gate_engine.register_result(
        stage_run.stage_run_id,
        gate_id="evidence.coverage",
        result=validation_result(passed=True),
    )

    transition = gate_engine.transition(
        stage_run.stage_run_id, StageState.APPROVED, actor="domain-owner"
    )

    assert transition.stage_run_id == stage_run.stage_run_id
    assert transition.from_state is StageState.DOMAIN_REVIEW
    assert transition.to_state is StageState.APPROVED
    assert transition.actor == "domain-owner"
    assert transition.gate_run_ids == [gate_run.gate_run_id]
    assert transition.created_at.tzinfo is not None
    assert gate_engine.get_stage_run(stage_run.stage_run_id).state is StageState.APPROVED
    with pytest.raises(TransitionBlocked, match="not allowed"):
        gate_engine.transition(
            stage_run.stage_run_id, StageState.RELEASED, actor="release-owner"
        )

from __future__ import annotations

from aifde.domain.stages import StageRun, StageState
from aifde.gates.definitions import GateDefinition
from aifde.gates.engine import GateEngine
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


def _passed_result(
    *,
    artifact_hash: str = "artifact-hash-1",
    validator_version: str = "1.0.0",
) -> ValidationResult:
    return ValidationResult(
        passed=True,
        violations=[],
        warnings=[],
        evidence_refs=["snapshot-1"],
        validator_version=validator_version,
        input_hashes={"artifact-1": artifact_hash},
    )


def _engine_with_completed_gate() -> GateEngine:
    engine = GateEngine()
    stage_run = StageRun(
            stage_run_id="run-1",
            project_id="project-1",
            stage_id="decision.contract",
            state=StageState.DOMAIN_REVIEW,
            output_artifact_ids=["artifact-1"],
            evidence_refs=["snapshot-1"],
        )
    context = ValidationContext(
        stage_run_id="run-1",
        artifact_ids=["artifact-1"],
        evidence_snapshot_id="snapshot-1",
        evidence_snapshot_hash="snapshot-hash-1",
        configuration={"threshold": 0.95},
    )
    engine.register_stage_run(stage_run, builder_actor="builder-1", validation_context=context)
    for gate_id in APPROVAL_GATES:
        engine.register_result(
            "run-1",
            gate_id=gate_id,
            result=_passed_result(),
            context=context,
        )
    return engine


def test_artifact_change_invalidates_old_gate_result():
    """Ignoring a changed artifact hash would approve stale validation evidence."""
    engine = _engine_with_completed_gate()

    assert engine.invalidate_for_artifact_change("artifact-1", "new-hash") == len(APPROVAL_GATES)
    decision = engine.can_transition("run-1", StageState.APPROVED)

    assert decision.allowed is False
    assert set(decision.blocking_gate_ids) == set(APPROVAL_GATES)


def test_evidence_snapshot_change_invalidates_old_gate_result():
    """Ignoring evidence snapshot changes would retain unsupported passed gates."""
    engine = _engine_with_completed_gate()

    assert engine.invalidate_for_evidence_snapshot_change("snapshot-1", "snapshot-2") == len(APPROVAL_GATES)

    assert engine.can_transition("run-1", StageState.APPROVED).allowed is False


def test_gate_definition_version_change_invalidates_old_gate_result():
    """Ignoring definition versions would apply a former gate policy to new policy."""
    engine = _engine_with_completed_gate()
    definition = engine.get_definition("evidence.coverage")

    engine.register_definition(definition.model_copy(update={"version": "2.0.0"}))

    assert engine.can_transition("run-1", StageState.APPROVED).allowed is False


def test_validator_version_change_invalidates_old_gate_result():
    """Ignoring validator versions would treat earlier validator output as current."""
    engine = _engine_with_completed_gate()
    definition = engine.get_definition("evidence.coverage")
    engine.register_definition(
        GateDefinition(
            gate_id=definition.gate_id,
            category=definition.category,
            severity=definition.severity,
            version=definition.version,
            validator_version="2.0.0",
        )
    )

    assert engine.can_transition("run-1", StageState.APPROVED).allowed is False


def test_configuration_change_invalidates_old_gate_result():
    """Ignoring configuration provenance would reuse a pass from different rules."""
    engine = _engine_with_completed_gate()

    assert engine.invalidate_for_configuration_change(
        "run-1", {"threshold": 0.99}
    ) == len(APPROVAL_GATES)

    assert engine.can_transition("run-1", StageState.APPROVED).allowed is False

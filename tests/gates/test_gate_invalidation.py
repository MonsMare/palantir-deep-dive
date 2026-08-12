from __future__ import annotations

from aifde.domain.stages import StageRun, StageState
from aifde.gates.definitions import GateDefinition
from aifde.gates.engine import GateEngine
from aifde.gates.validators import ValidationResult


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
    engine.register_stage_run(
        StageRun(
            stage_run_id="run-1",
            project_id="project-1",
            stage_id="decision.contract",
            state=StageState.DOMAIN_REVIEW,
            output_artifact_ids=["artifact-1"],
            evidence_refs=["snapshot-1"],
        )
    )
    engine.register_result("run-1", gate_id="evidence.coverage", result=_passed_result())
    return engine


def test_artifact_change_invalidates_old_gate_result():
    """Ignoring a changed artifact hash would approve stale validation evidence."""
    engine = _engine_with_completed_gate()

    assert engine.invalidate_for_artifact_change("artifact-1", "new-hash") == 1
    decision = engine.can_transition("run-1", StageState.APPROVED)

    assert decision.allowed is False
    assert decision.blocking_gate_ids == ["evidence.coverage"]


def test_evidence_snapshot_change_invalidates_old_gate_result():
    """Ignoring evidence snapshot changes would retain unsupported passed gates."""
    engine = _engine_with_completed_gate()

    assert engine.invalidate_for_evidence_snapshot_change("snapshot-1", "snapshot-2") == 1

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

from __future__ import annotations

import pytest

from aifde.domain.artifacts import Artifact
from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.cli import transition_stage_run
from aifde.gates.engine import GateEngine, TransitionBlocked
from aifde.gates.validators import ValidationContext, ValidationResult
from aifde.registry.sqlite import SQLiteRegistry
from aifde.release import ReleaseManager


APPROVAL_GATES = (
    "reality.consistency",
    "evidence.coverage",
    "semantic.integrity",
    "data.quality",
    "executable.readiness",
    "adversarial.challenge",
    "business.exception_coverage",
    "release.governance",
)


def _artifact(version: str = "1.0.0") -> Artifact:
    return Artifact.build(
        artifact_id="artifact-1",
        project_id="project-1",
        kind="DecisionContract",
        version=version,
        owner="builder-1",
        content={"decision": "prioritize", "version": version},
    )


def _ready_stage(engine: GateEngine, artifact: Artifact, *, run_id: str) -> StageRun:
    stage = StageRun(
        stage_run_id=run_id,
        project_id=artifact.project_id,
        stage_id="decision.contract",
        state=StageState.DOMAIN_REVIEW,
        output_artifact_ids=[artifact.artifact_id],
        evidence_refs=[f"snapshot-{run_id}"],
    )
    context = ValidationContext(
        stage_run_id=run_id,
        artifact_ids=[artifact.artifact_id],
        evidence_snapshot_id=f"snapshot-{run_id}",
        evidence_snapshot_hash=f"hash-{run_id}",
        configuration={"fixture": run_id},
    )
    engine.register_stage_run(stage, builder_actor="builder-1", validation_context=context)
    for gate_id in APPROVAL_GATES:
        engine.register_result(
            run_id,
            gate_id=gate_id,
            result=ValidationResult(
                passed=True,
                evidence_refs=[context.evidence_snapshot_id],
                validator_version=engine.get_definition(gate_id).validator_version,
                input_hashes={artifact.artifact_id: artifact.content_hash},
            ),
            context=context,
            gate_result=GateResult.PASSED,
        )
    engine.transition(run_id, StageState.APPROVED, actor="domain-owner-1")
    engine.transition(run_id, StageState.RELEASE_CANDIDATE, actor="release-owner-1")
    return stage


def test_failed_gate_cannot_be_promoted_into_a_release(tmp_path) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    try:
        artifact = _artifact()
        registry.artifacts.put(artifact)
        engine = GateEngine()
        stage = StageRun(
            stage_run_id="blocked-run",
            project_id=artifact.project_id,
            stage_id="decision.contract",
            state=StageState.DOMAIN_REVIEW,
            output_artifact_ids=[artifact.artifact_id],
            evidence_refs=["snapshot-blocked"],
        )
        context = ValidationContext(
            stage_run_id=stage.stage_run_id,
            artifact_ids=[artifact.artifact_id],
            evidence_snapshot_id="snapshot-blocked",
            evidence_snapshot_hash="hash-blocked",
            configuration={"fixture": "blocked"},
        )
        engine.register_stage_run(stage, builder_actor="builder-1", validation_context=context)
        for gate_id in APPROVAL_GATES:
            passed = gate_id != "evidence.coverage"
            engine.register_result(
                stage.stage_run_id,
                gate_id=gate_id,
                result=ValidationResult(
                    passed=passed,
                    violations=[] if passed else ["missing evidence"],
                    evidence_refs=[context.evidence_snapshot_id],
                    validator_version=engine.get_definition(gate_id).validator_version,
                    input_hashes={artifact.artifact_id: artifact.content_hash},
                ),
                context=context,
                gate_result=GateResult.PASSED if passed else GateResult.FAILED,
            )

        manager = ReleaseManager(registry, engine)
        with pytest.raises(TransitionBlocked, match="blocked"):
            manager.build(artifact.project_id, [artifact.artifact_id])
        with pytest.raises(TransitionBlocked, match="blocked"):
            transition_stage_run(
                engine,
                stage_run_id=stage.stage_run_id,
                target=StageState.APPROVED,
                actor="domain-owner-1",
            )
    finally:
        registry.close()


def test_ready_stage_is_releasable_only_after_the_gate_engine_approvals(tmp_path) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    try:
        artifact = _artifact()
        registry.artifacts.put(artifact)
        engine = GateEngine()
        _ready_stage(engine, artifact, run_id="run-ready")
        package = ReleaseManager(registry, engine).build(
            artifact.project_id, [artifact.artifact_id]
        )
        assert package.gate_run_ids
        assert package.passed_gate_run_ids == package.gate_run_ids
        assert package.approval_ids
    finally:
        registry.close()


def test_release_verification_and_rollback_are_append_only(tmp_path) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    try:
        registry.artifacts.put(_artifact("0.9.0"))
        current = _artifact("1.0.0")
        registry.artifacts.put(current)
        engine = GateEngine()
        _ready_stage(engine, current, run_id="run-rollback")
        manager = ReleaseManager(registry, engine)
        package = manager.build(current.project_id, [current.artifact_id])

        assert manager.verify(package.package_id).passed is True
        result = manager.rollback(package.package_id)
        assert result.restored_artifact_ids == [current.artifact_id]
        assert engine.get_stage_run("run-rollback").state is StageState.REMEDIATION
        assert registry.artifacts.get("project-1", "artifact-1").version == "1.0.1"
        assert registry.artifacts.get("project-1", "artifact-1", version="0.9.0").content == {
            "decision": "prioritize",
            "version": "0.9.0",
        }
        assert manager.verify(package.package_id).passed is False
    finally:
        registry.close()

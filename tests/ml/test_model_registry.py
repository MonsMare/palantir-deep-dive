from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aifde.ml.evaluation import EvaluationReport
from aifde.ml.adapters import BaselineMedianAdapter, TabularModelAdapter
from aifde.ml.registry import ModelArtifact, ModelRegistry


UTC = timezone.utc


def _artifact(version: str) -> ModelArtifact:
    return ModelArtifact.create(
        model_id="supplier-delay-model",
        model_version=version,
        feature_definition_id="supplier-delay-features",
        feature_definition_version="1.0.0",
        ontology_release_id="ontology-release:1",
        training_snapshot_id="feature-snapshot:train",
        training_data_hash="a" * 64,
        code_version="code-v1",
        artifact_uri=f"local://models/{version}",
        model_type="tabular-regressor",
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
    )


def _report(version: str = "candidate-v1", release_eligible: bool = True) -> EvaluationReport:
    return EvaluationReport(
        report_id="evaluation:1",
        model_id="supplier-delay-model",
        model_version=version,
        baseline_mae=4.0,
        model_mae=2.0,
        p80_coverage=0.9,
        calibration_error=0.1,
        temporal_windows=("2026-08",),
        leakage_passed=True,
        release_eligible=release_eligible,
        metrics={"rows": 10},
        report_hash="b" * 64,
    )


def test_model_registry_is_append_only_and_promote_requires_evaluation() -> None:
    registry = ModelRegistry()
    artifact = _artifact("candidate-v1")
    registry.register(artifact, runtime_object={"kind": "test"})

    with pytest.raises(ValueError, match="evaluation"):
        registry.promote(artifact.model_id, artifact.model_version, None)

    promoted = registry.promote(artifact.model_id, artifact.model_version, _report())
    assert promoted.status == "approved"
    assert registry.current(artifact.model_id).model_version == "candidate-v1"
    assert registry.verify(artifact)


def test_model_registry_rejects_weak_candidate_and_supports_rollback() -> None:
    registry = ModelRegistry()
    first = _artifact("v1")
    second = _artifact("v2")
    registry.register(first)
    registry.promote(first.model_id, first.model_version, _report("v1"))
    registry.register(second)

    with pytest.raises(ValueError, match="release eligible"):
        registry.promote(second.model_id, second.model_version, _report("v2", False))
    registry.promote(second.model_id, second.model_version, _report("v2"))
    rolled_back = registry.rollback(second.model_id, "v1", actor="release-owner-1")
    assert rolled_back.model_version == "v1"
    assert registry.current("supplier-delay-model").model_version == "v1"


def test_model_artifact_tampering_is_detected() -> None:
    artifact = _artifact("tamper-v1")
    registry = ModelRegistry()
    registry.register(artifact)

    tampered = artifact.model_copy(update={"artifact_uri": "local://forged"})
    assert not registry.verify(tampered)
    with pytest.raises(ValueError, match="immutable"):
        registry.register(tampered)


def test_tabular_adapter_and_baseline_are_replayable() -> None:
    rows = [
        {"risk": 0.0, "capacity": 10.0},
        {"risk": 1.0, "capacity": 8.0},
        {"risk": 2.0, "capacity": 6.0},
    ]
    adapter = TabularModelAdapter(("risk", "capacity"), model_version="hgb-v1")
    fitted = adapter.fit(rows, (1.0, 2.0, 3.0))
    predictions = adapter.predict(fitted, rows)
    assert len(predictions) == 3
    assert fitted.training_data_hash
    assert adapter.explain(fitted, rows[0])["model_version"] == "hgb-v1"

    baseline = BaselineMedianAdapter().fit(rows, (1.0, 2.0, 3.0))
    assert BaselineMedianAdapter().predict(baseline, rows) == (2.0, 2.0, 2.0)

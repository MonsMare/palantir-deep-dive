from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from aifde.builder.flow import BuilderRunConfig, EvidenceDrivenOntologyBuilder
from aifde.ontology.computation import FeatureDefinition, LabelDefinition
from aifde.runtime.decisions import DecisionOption, DecisionRuntime
from aifde.runtime.features import FeatureRuntime
from aifde.runtime.labels import LabelRuntime
from aifde.runtime.predictions import PredictionRuntime
from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


UTC = timezone.utc
SUPPLIER_ROOT = Path("projects/supplier-delay-builder-demo")
SOFTWARE_FIXTURE = Path("tests/domains/fixtures/software_requirements.json")


def _supplier_features() -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="supplier-delay-runtime-features",
        entity_type="PurchaseOrder",
        grain="purchase_order",
        feature_fields=("supplier_id", "promised_delivery_date", "actual_delivery_date"),
        computation_expression="point_in_time:purchase_order",
        time_window="as_of_time",
        availability_lag_seconds=0,
        missing_policy="unknown",
        version="1.0.0",
        ontology_version="0.1.0",
        leakage_policy="available_at <= as_of_time",
        lineage_refs=("lineage:feature-definition",),
    )


def test_feature_runtime_uses_domain_primary_key_and_excludes_future_available_fields() -> None:
    result = run_supplier_delay_builder_demo(SUPPLIER_ROOT)
    package = result.release_package
    assert package is not None

    snapshot = FeatureRuntime().materialize(
        result.compile_result,
        _supplier_features(),
        ontology_release_id=package.release_id,
        as_of_time=datetime(2026, 9, 7, 23, 59, tzinfo=UTC),
    )

    po_one = next(item for item in snapshot.values if item.entity_id == "PO-001")
    assert "actual_delivery_date" not in po_one.values
    assert po_one.available_at <= snapshot.as_of_time
    assert snapshot.data_product_hash == result.compile_result.artifact_hashes["canonical_product"]
    assert po_one.source_evidence_refs


def test_feature_runtime_is_not_supplier_keyed_for_software_pack(tmp_path: Path) -> None:
    result = EvidenceDrivenOntologyBuilder().run(
        BuilderRunConfig(
            project_id="runtime-software",
            domain="software-delivery",
            domain_pack_id="software-delivery",
            ontology_version="0.1.0",
            actor_id="builder-1",
            source_paths=(str(SOFTWARE_FIXTURE),),
            approval_actor="domain-owner-1",
            persistence_path=str(tmp_path / "runtime.db"),
        )
    )
    definition = FeatureDefinition(
        feature_id="requirement-runtime-features",
        entity_type="Requirement",
        grain="requirement",
        feature_fields=("title", "priority"),
        computation_expression="point_in_time:requirement",
        time_window="as_of_time",
        availability_lag_seconds=0,
        missing_policy="fail",
        version="1.0.0",
        ontology_version="0.1.0",
        leakage_policy="available_at <= as_of_time",
        lineage_refs=("lineage:requirement-feature",),
    )

    snapshot = FeatureRuntime().materialize(
        result.compile_result,
        definition,
        ontology_release_id=result.release_package.release_id,
        as_of_time=datetime(2026, 8, 14, 23, 59, tzinfo=UTC),
    )
    assert {item.entity_id for item in snapshot.values} == {"REQ-001", "REQ-002"}


def test_label_runtime_keeps_future_outcome_separate_from_feature_snapshot() -> None:
    result = run_supplier_delay_builder_demo(SUPPLIER_ROOT)
    package = result.release_package
    assert package is not None
    definition = LabelDefinition(
        label_id="supplier-delay-label-runtime",
        entity_type="PurchaseOrder",
        grain="purchase_order",
        target_field="actual_delivery_date",
        label_window="future_delivery_event",
        outcome_available_lag_seconds=0,
        missing_policy="unknown",
        version="1.0.0",
        ontology_version="0.1.0",
        lineage_refs=("lineage:delivery-outcome",),
    )

    snapshot = LabelRuntime().materialize(
        result.compile_result,
        definition,
        ontology_release_id=package.release_id,
        feature_as_of_time=datetime(2026, 9, 7, 23, 59, tzinfo=UTC),
        label_as_of_time=datetime(2026, 9, 8, 12, tzinfo=UTC),
    )
    po_one = next(item for item in snapshot.values if item.entity_id == "PO-001")
    assert po_one.value == "2026-09-07"
    assert po_one.available_at > snapshot.feature_as_of_time


class ThresholdModel:
    def predict(self, values: dict[str, Any]) -> dict[str, float]:
        return {
            "value": 0.9 if values.get("supplier_id") == "supplier:acme" else 0.1,
            "confidence": 0.8,
        }


def test_prediction_runtime_binds_model_output_to_feature_snapshot() -> None:
    result = run_supplier_delay_builder_demo(SUPPLIER_ROOT)
    package = result.release_package
    assert package is not None
    snapshot = FeatureRuntime().materialize(
        result.compile_result,
        _supplier_features(),
        ontology_release_id=package.release_id,
        as_of_time=datetime(2026, 9, 7, 23, 59, tzinfo=UTC),
    )

    predictions = PredictionRuntime().predict(
        snapshot,
        ThresholdModel(),
        model_id="supplier-delay-model",
        model_version="model-v1",
        target="supplier_delay_probability",
    )
    assert len(predictions) == len(snapshot.values)
    assert all(item.feature_snapshot_id == snapshot.snapshot_id for item in predictions)
    assert all(item.model_version == "model-v1" for item in predictions)
    assert next(item for item in predictions if item.entity_id == "PO-001").value == 0.9


def test_decision_runtime_ranks_only_feasible_options_deterministically() -> None:
    result = run_supplier_delay_builder_demo(SUPPLIER_ROOT)
    package = result.release_package
    assert package is not None
    snapshot = FeatureRuntime().materialize(
        result.compile_result,
        _supplier_features(),
        ontology_release_id=package.release_id,
        as_of_time=datetime(2026, 9, 7, 23, 59, tzinfo=UTC),
    )
    predictions = PredictionRuntime().predict(
        snapshot,
        ThresholdModel(),
        model_id="supplier-delay-model",
        model_version="model-v1",
        target="supplier_delay_probability",
    )
    target_prediction = next(item for item in predictions if item.entity_id == "PO-001")
    options = (
        DecisionOption(
            option_id="expedite",
            entity_id="PO-001",
            action_type="expedite_supplier_followup",
            objective_value=2.0,
            constraint_status="feasible",
            prediction_ids=(target_prediction.prediction_id,),
            parameters={"channel": "phone"},
        ),
        DecisionOption(
            option_id="wait",
            entity_id="PO-001",
            action_type="wait",
            objective_value=0.5,
            constraint_status="infeasible",
            prediction_ids=(target_prediction.prediction_id,),
            parameters={},
        ),
    )
    decisions = DecisionRuntime().rank(
        snapshot,
        predictions,
        options,
        objective="minimize",
    )
    assert len(decisions) == 1
    assert decisions[0].action_type == "expedite_supplier_followup"
    assert decisions[0].rank == 1
    assert decisions[0].constraint_status == "feasible"


def test_runtime_rejects_cross_ontology_version_inputs() -> None:
    result = run_supplier_delay_builder_demo(SUPPLIER_ROOT)
    package = result.release_package
    assert package is not None
    with pytest.raises(ValueError, match="ontology_version"):
        FeatureRuntime().materialize(
            result.compile_result,
            _supplier_features().model_copy(update={"ontology_version": "0.2.0"}),
            ontology_release_id=package.release_id,
            as_of_time=datetime(2026, 9, 7, 23, 59, tzinfo=UTC),
        )

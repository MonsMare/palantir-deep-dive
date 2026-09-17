from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from aifde.ontology.computation import (
    ActionOutcomeLink,
    ComputationChainValidator,
    DecisionCandidate,
    FeatureDefinition,
    FeatureMaterializer,
    FeedbackLink,
    GovernedActionRequest,
    LabelDefinition,
    LabelMaterializer,
    LabelSnapshot,
    PredictionArtifact,
)
from aifde.policy.capabilities import ActorRole, ApprovedActionRecord
from aifde.tools.actions import ActionBroker
from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


PROJECT_ROOT = Path("projects/supplier-delay-builder-demo")
AS_OF = datetime(2026, 9, 7, 23, 59, tzinfo=timezone.utc)


def _feature_definition() -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="supplier-delay-features",
        entity_type="PurchaseOrder",
        grain="purchase_order",
        feature_fields=(
            "supplier_id",
            "promised_delivery_date",
            "actual_delivery_date",
            "delay_days",
            "delay_state",
        ),
        computation_expression="point_in_time:PurchaseOrder.delivery_status",
        time_window="as_of_time",
        availability_lag_seconds=0,
        missing_policy="unknown",
        version="1.0.0",
        ontology_version="0.1.0",
        leakage_policy="available_at <= as_of_time; future actual delivery is excluded",
        lineage_refs=("urn:lineage:canonical-purchase-order",),
    )


def test_feature_snapshot_is_point_in_time_and_lineage_closed() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None

    snapshot = FeatureMaterializer().materialize(
        result.compile_result,
        _feature_definition(),
        ontology_release_id=package.release_id,
        as_of_time=AS_OF,
    )

    po_one = next(item for item in snapshot.values if item.entity_id == "PO-001")
    assert po_one.values["delay_state"] == "Unknown"
    assert "actual_delivery_date" not in po_one.values
    assert po_one.available_at <= AS_OF
    assert snapshot.data_product_hash == result.compile_result.artifact_hashes["canonical_product"]
    assert snapshot.ontology_release_id == package.release_id
    assert po_one.source_evidence_refs


def test_prediction_decision_action_feedback_chain_is_bound() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None
    snapshot = FeatureMaterializer().materialize(
        result.compile_result,
        _feature_definition(),
        ontology_release_id=package.release_id,
        as_of_time=AS_OF,
    )

    prediction = PredictionArtifact(
        prediction_id="prediction:PO-001:2026-09-07",
        entity_id="PO-001",
        target="supplier_delay_probability",
        value=0.82,
        model_id="supplier-delay-model",
        model_version="model-1.0.0",
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        feature_snapshot_id=snapshot.snapshot_id,
        feature_definition_version="1.0.0",
        as_of_time=AS_OF,
        generated_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        confidence=0.91,
        lineage_refs=("urn:lineage:prediction",),
    )
    decision = DecisionCandidate(
        decision_id="decision:PO-001:expedite",
        entity_id="PO-001",
        action_type="expedite_supplier_followup",
        objective="minimize_expected_delay_cost",
        objective_value=0.82,
        rank=1,
        constraint_status="feasible",
        prediction_ids=(prediction.prediction_id,),
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        feature_snapshot_id=snapshot.snapshot_id,
        model_versions=(prediction.model_version,),
        as_of_time=AS_OF,
        lineage_refs=("urn:lineage:decision",),
    )
    action = GovernedActionRequest(
        action_id="action:PO-001:expedite",
        decision_id=decision.decision_id,
        target_id="PO-001",
        action_type=decision.action_type,
        parameters={"contact_channel": "procurement-queue"},
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        prediction_ids=decision.prediction_ids,
        feature_snapshot_id=snapshot.snapshot_id,
        as_of_time=AS_OF,
        requested_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        requested_by="procurement-agent",
        policy_id="policy:procurement-action",
        policy_version="1.0.0",
        approval_id="approval:PO-001:expedite",
        approval_status="approved",
        validation_id="validation:PO-001:expedite",
        validation_status="passed",
        lineage_refs=("urn:lineage:action",),
    )
    outcome = ActionOutcomeLink(
        outcome_id="outcome:PO-001:expedite",
        action_id=action.action_id,
        decision_id=decision.decision_id,
        target_id="PO-001",
        status="succeeded",
        external_ref="mock://procurement/PO-001",
        executed_at=datetime(2026, 9, 8, 12, 1, tzinfo=timezone.utc),
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        prediction_ids=(prediction.prediction_id,),
        feature_snapshot_id=snapshot.snapshot_id,
        lineage_refs=("urn:lineage:outcome",),
    )
    feedback = FeedbackLink(
        feedback_id="feedback:PO-001:expedite",
        artifact_kind="ActionOutcome",
        artifact_id=outcome.outcome_id,
        value={"supplier_confirmed": True, "actual_delay_days": 2},
        source="procurement-operator",
        created_at=datetime(2026, 9, 10, 12, tzinfo=timezone.utc),
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        feature_snapshot_id=snapshot.snapshot_id,
        as_of_time=AS_OF,
        prediction_id=prediction.prediction_id,
        decision_id=decision.decision_id,
        action_id=action.action_id,
        lineage_refs=("urn:lineage:feedback",),
    )

    report = ComputationChainValidator.validate(
        snapshot, feedback, outcome, action, decision, prediction
    )
    assert report.passed is True
    assert report.chain_id


def test_governed_request_can_be_adapted_without_losing_context() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None
    snapshot = FeatureMaterializer().materialize(
        result.compile_result,
        _feature_definition(),
        ontology_release_id=package.release_id,
        as_of_time=AS_OF,
    )
    action = GovernedActionRequest(
        action_id="action:adapter",
        decision_id="decision:adapter",
        target_id="PO-001",
        action_type="ReplanSprint",
        parameters={"capacity": 8},
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        prediction_ids=("prediction:adapter",),
        feature_snapshot_id=snapshot.snapshot_id,
        as_of_time=AS_OF,
        requested_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        requested_by="builder-1",
        policy_id="mock-actions",
        policy_version="1",
        approval_id="approval:adapter",
        approval_status="approved",
        validation_id="validation:adapter",
        validation_status="passed",
        lineage_refs=("urn:lineage:adapter",),
    )
    legacy = action.to_legacy_action_request(audit_ref="audit:adapter", audit_actor="audit-service")
    assert legacy.parameters["ontology_release_id"] == package.release_id
    assert legacy.parameters["feature_snapshot_id"] == snapshot.snapshot_id


def test_governed_action_requires_a_complete_chain() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None
    snapshot = FeatureMaterializer().materialize(
        result.compile_result,
        _feature_definition(),
        ontology_release_id=package.release_id,
        as_of_time=AS_OF,
    )
    action = GovernedActionRequest(
        action_id="action:missing-chain",
        decision_id="decision:missing",
        target_id="PO-001",
        action_type="expedite_supplier_followup",
        parameters={},
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        prediction_ids=("prediction:missing",),
        feature_snapshot_id=snapshot.snapshot_id,
        as_of_time=AS_OF,
        requested_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        requested_by="procurement-agent",
        policy_id="policy:procurement-action",
        policy_version="1.0.0",
        approval_id="approval:missing-chain",
        approval_status="approved",
        validation_id="validation:missing-chain",
        validation_status="passed",
        lineage_refs=("urn:lineage:action",),
    )
    with pytest.raises(ValueError, match="missing decision|missing predictions"):
        ComputationChainValidator.validate(snapshot, action)


def test_governed_action_uses_existing_approval_and_action_broker() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None
    snapshot = FeatureMaterializer().materialize(
        result.compile_result,
        _feature_definition(),
        ontology_release_id=package.release_id,
        as_of_time=AS_OF,
    )
    prediction = PredictionArtifact(
        prediction_id="prediction:broker",
        entity_id="PO-001",
        target="supplier_delay_probability",
        value=0.8,
        model_id="supplier-delay-model",
        model_version="model-1.0.0",
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        feature_snapshot_id=snapshot.snapshot_id,
        feature_definition_version="1.0.0",
        as_of_time=AS_OF,
        generated_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        confidence=0.8,
        lineage_refs=("urn:lineage:prediction",),
    )
    decision = DecisionCandidate(
        decision_id="decision:broker",
        entity_id="PO-001",
        action_type="ReplanSprint",
        objective="minimize_expected_delay_cost",
        objective_value=0.8,
        rank=1,
        constraint_status="feasible",
        prediction_ids=(prediction.prediction_id,),
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        feature_snapshot_id=snapshot.snapshot_id,
        model_versions=(prediction.model_version,),
        as_of_time=AS_OF,
        lineage_refs=("urn:lineage:decision",),
    )
    action = GovernedActionRequest(
        action_id="action:broker",
        decision_id=decision.decision_id,
        target_id="PO-001",
        action_type="ReplanSprint",
        parameters={"capacity": 8},
        ontology_release_id=package.release_id,
        ontology_version="0.1.0",
        prediction_ids=decision.prediction_ids,
        feature_snapshot_id=snapshot.snapshot_id,
        as_of_time=AS_OF,
        requested_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        requested_by="builder-1",
        policy_id="mock-actions",
        policy_version="1",
        approval_id="approval:broker",
        approval_status="approved",
        validation_id="validation:broker",
        validation_status="passed",
        lineage_refs=("urn:lineage:action",),
    )
    broker = ActionBroker(
        approved_actions=[
            ApprovedActionRecord(
                action_id=action.action_id,
                action_type="ReplanSprint",
                execution_mode="mock",
                requested_by="builder-1",
                validation_status="passed",
                approval_id=action.approval_id,
                approval_actor=action.approval_actor,
                approval_role=ActorRole.DOMAIN_OWNER,
                approval_status="approved",
            )
        ]
    )
    outcome, link = broker.execute_governed(
        action,
        snapshot,
        actor="release-owner-1",
        decision=decision,
        predictions=[prediction],
    )
    assert outcome.status == "succeeded"
    assert link.action_id == action.action_id
    assert link.feature_snapshot_id == snapshot.snapshot_id


def test_chain_rejects_cross_release_prediction() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None
    snapshot = FeatureMaterializer().materialize(
        result.compile_result,
        _feature_definition(),
        ontology_release_id=package.release_id,
        as_of_time=AS_OF,
    )
    prediction = PredictionArtifact(
        prediction_id="prediction:bad",
        entity_id="PO-001",
        target="supplier_delay_probability",
        value=0.8,
        model_id="supplier-delay-model",
        model_version="model-1.0.0",
        ontology_release_id="ontology-release:other",
        ontology_version="0.1.0",
        feature_snapshot_id=snapshot.snapshot_id,
        feature_definition_version="1.0.0",
        as_of_time=AS_OF,
        generated_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        confidence=0.8,
        lineage_refs=("urn:lineage:prediction",),
    )

    with pytest.raises(ValueError, match="release"):
        ComputationChainValidator.validate(snapshot, prediction)


def test_label_contract_separates_future_outcome_from_features() -> None:
    definition = LabelDefinition(
        label_id="supplier-delay-label",
        entity_type="PurchaseOrder",
        grain="purchase_order",
        target_field="actual_delivery_date",
        label_window="future_delivery_event",
        outcome_available_lag_seconds=0,
        missing_policy="unknown",
        version="1.0.0",
        ontology_version="0.1.0",
        lineage_refs=("urn:lineage:delivery-event",),
    )
    assert definition.target_field == "actual_delivery_date"
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None
    labels = LabelMaterializer().materialize(
        result.compile_result,
        definition,
        ontology_release_id=package.release_id,
        feature_as_of_time=AS_OF,
        label_as_of_time=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    assert any(item.entity_id == "PO-001" for item in labels.values)
    with pytest.raises(ValueError, match="after"):
        LabelSnapshot(
            snapshot_id="labels:bad",
            label_definition_id=definition.label_id,
            label_definition_version=definition.version,
            ontology_release_id="ontology-release:1",
            ontology_version=definition.ontology_version,
            data_product_hash="a" * 64,
            feature_as_of_time=AS_OF,
            label_as_of_time=AS_OF,
            values=(),
            lineage_refs=definition.lineage_refs,
        )

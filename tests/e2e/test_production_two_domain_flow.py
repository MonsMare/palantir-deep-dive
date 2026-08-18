from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from aifde.actions.adapters import GovernedActionBroker, JsonlFileActionAdapter
from aifde.builder.flow import BuilderRunConfig, BuilderRunResult, EvidenceDrivenOntologyBuilder
from aifde.observability.audit import AppendOnlyAuditLog
from aifde.observability.metrics import MetricsRegistry
from aifde.ontology.computation import (
    ComputationChainValidator,
    FeatureDefinition,
    FeedbackLink,
    GovernedActionRequest,
)
from aifde.runtime.decisions import DecisionOption, DecisionRuntime
from aifde.runtime.features import FeatureRuntime
from aifde.runtime.predictions import PredictionRuntime
from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


UTC = timezone.utc
SOFTWARE_FIXTURE = Path("tests/domains/fixtures/software_requirements.json")
SUPPLIER_ROOT = Path("projects/supplier-delay-builder-demo")


class _RiskAdapter:
    def predict(self, values: dict[str, object]) -> dict[str, float]:
        return {"value": 0.9 if values else 0.5, "confidence": 0.8}


def _feature_definition(result: BuilderRunResult) -> FeatureDefinition:
    if result.domain_pack_id == "supplier-delay":
        entity_type = "PurchaseOrder"
        grain = "purchase_order"
        fields = ("supplier_id", "promised_delivery_date")
        feature_id = "supplier-delay-e2e-features"
    else:
        entity_type = "Requirement"
        grain = "requirement"
        fields = ("title", "priority")
        feature_id = "software-delivery-e2e-features"
    return FeatureDefinition(
        feature_id=feature_id,
        entity_type=entity_type,
        grain=grain,
        feature_fields=fields,
        computation_expression="point_in_time:ontology-object",
        time_window="as_of_time",
        availability_lag_seconds=0,
        missing_policy="unknown",
        version="1.0.0",
        ontology_version=result.compile_result.ontology_candidate.version,
        leakage_policy="available_at <= as_of_time",
        lineage_refs=(f"lineage:{result.domain_pack_id}:features",),
    )


def _run_decision_action_feedback(
    result: BuilderRunResult,
    *,
    as_of: datetime,
    action_path: Path,
    metrics: MetricsRegistry,
    audit: AppendOnlyAuditLog,
) -> None:
    package = result.release_package
    assert package is not None
    snapshot = FeatureRuntime().materialize(
        result.compile_result,
        _feature_definition(result),
        ontology_release_id=package.release_id,
        as_of_time=as_of,
    )
    metrics.increment("runtime.feature_snapshot", labels={"domain": result.domain_pack_id})
    audit.append(
        event_type="feature.snapshot",
        actor="runtime",
        subject_id=snapshot.snapshot_id,
        payload=snapshot.model_dump(mode="json"),
    )
    predictions = PredictionRuntime().predict(
        snapshot,
        _RiskAdapter(),
        model_id=f"{result.domain_pack_id}-risk-model",
        model_version="1.0.0",
        target="operational_risk",
        generated_at=as_of + timedelta(hours=1),
    )
    assert predictions
    metrics.increment("runtime.prediction", amount=len(predictions), labels={"domain": result.domain_pack_id})
    prediction = predictions[0]
    decision = DecisionRuntime().rank(
        snapshot,
        predictions,
        [
            DecisionOption(
                option_id="escalate",
                entity_id=prediction.entity_id,
                action_type="escalate",
                objective_value=1.0,
                constraint_status="feasible",
                prediction_ids=(prediction.prediction_id,),
                parameters={"channel": "operations-queue"},
            )
        ],
    )[0]
    metrics.increment("runtime.decision", labels={"domain": result.domain_pack_id})
    action = GovernedActionRequest(
        action_id=f"action:{result.domain_pack_id}:{prediction.entity_id}",
        decision_id=decision.decision_id,
        target_id=decision.entity_id,
        action_type=decision.action_type,
        parameters=decision.parameters,
        ontology_release_id=package.release_id,
        ontology_version=package.ontology_version,
        prediction_ids=decision.prediction_ids,
        feature_snapshot_id=snapshot.snapshot_id,
        as_of_time=as_of,
        requested_at=as_of + timedelta(hours=1),
        requested_by="decision-agent",
        policy_id=f"policy:{result.domain_pack_id}",
        policy_version="1.0.0",
        approval_id=f"approval:{result.domain_pack_id}",
        approval_status="approved",
        validation_id=f"validation:{result.domain_pack_id}",
        validation_status="passed",
        lineage_refs=(f"lineage:{result.domain_pack_id}:action",),
    )
    broker = GovernedActionBroker(adapter=JsonlFileActionAdapter(action_path))
    broker.dry_run(action, actor="release-owner-1")
    execution = broker.execute_with_chain(
        snapshot,
        predictions,
        decision,
        action,
        actor="release-owner-1",
    )
    assert execution.reconciliation.status == "matched"
    metrics.increment("runtime.action", labels={"domain": result.domain_pack_id})
    feedback = FeedbackLink(
        feedback_id=f"feedback:{result.domain_pack_id}:{prediction.entity_id}",
        artifact_kind="ActionOutcome",
        artifact_id=execution.outcome_link.outcome_id,
        value={"status": execution.receipt.status},
        source="external-file-adapter",
        created_at=execution.receipt.executed_at,
        ontology_release_id=package.release_id,
        ontology_version=package.ontology_version,
        feature_snapshot_id=snapshot.snapshot_id,
        as_of_time=as_of,
        prediction_id=prediction.prediction_id,
        decision_id=decision.decision_id,
        action_id=action.action_id,
        lineage_refs=(f"lineage:{result.domain_pack_id}:feedback",),
    )
    report = ComputationChainValidator.validate(
        snapshot, *predictions, decision, action, execution.outcome_link, feedback
    )
    assert report.passed
    metrics.increment("runtime.feedback", labels={"domain": result.domain_pack_id})
    audit.append(
        event_type="action.outcome",
        actor="external-file-adapter",
        subject_id=execution.outcome_link.outcome_id,
        payload=execution.outcome_link.model_dump(mode="json"),
    )


def test_supplier_delay_completes_production_chain(tmp_path: Path) -> None:
    metrics = MetricsRegistry()
    audit = AppendOnlyAuditLog()
    result = run_supplier_delay_builder_demo(
        SUPPLIER_ROOT,
        persistence_path=str(tmp_path / "supplier.db"),
    )
    assert result.state == "released"
    _run_decision_action_feedback(
        result,
        as_of=datetime(2026, 9, 7, 23, 59, tzinfo=UTC),
        action_path=tmp_path / "supplier-actions.jsonl",
        metrics=metrics,
        audit=audit,
    )
    assert metrics.snapshot()["runtime.feedback|domain=supplier-delay"] == 1
    assert audit.verify()


def test_software_delivery_completes_same_chain_without_supplier_keys(tmp_path: Path) -> None:
    metrics = MetricsRegistry()
    audit = AppendOnlyAuditLog()
    result = EvidenceDrivenOntologyBuilder().run(
        BuilderRunConfig(
            project_id="software-e2e",
            domain="software-delivery",
            domain_pack_id="software-delivery",
            ontology_version="0.1.0",
            actor_id="builder-1",
            source_paths=(str(SOFTWARE_FIXTURE),),
            approval_actor="domain-owner-1",
            persistence_path=str(tmp_path / "software.db"),
        )
    )
    assert result.state == "released"
    _run_decision_action_feedback(
        result,
        as_of=datetime(2026, 8, 14, 23, 59, tzinfo=UTC),
        action_path=tmp_path / "software-actions.jsonl",
        metrics=metrics,
        audit=audit,
    )
    assert metrics.snapshot()["runtime.feedback|domain=software-delivery"] == 1
    assert audit.verify()

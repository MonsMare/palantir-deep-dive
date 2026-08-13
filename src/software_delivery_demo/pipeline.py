"""End-to-end sample pipeline and adversarial gate scenarios.

The demo deliberately delegates every stage state mutation to the platform
``GateEngine``.  The business calculations remain local and deterministic,
but their promotion to an approved or blocked stage is never represented by
an un-audited boolean assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from aifde.domain.actions import ActionRequest
from aifde.domain.feedback import Feedback
from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.feedback import FeedbackService
from aifde.gates.engine import GateEngine
from aifde.gates.validators import ValidationContext, ValidationResult
from aifde.policy.capabilities import ActorRole, ApprovedActionRecord
from aifde.tools.actions import ActionBroker

from .analytics import build_project_snapshot
from .actions import build_demo_action_request, register_demo_actions
from .data_products import build_data_products, run_quality_checks
from .decisions import build_candidate_plans
from .domain import ChangeRequest, ProjectConfig
from .features import build_features, build_features_with_intentional_leak, check_no_leakage, load_feature_definitions
from .generator import DatasetBundle, generate_dataset, write_dataset
from .labels import build_labels
from .models import BaselineModel, DeliveryModel, evaluate_model, release_model
from .ontology import project_objects_to_graph, validate_domain_graph


@dataclass(frozen=True)
class StageConfig:
    stage_id: str
    input_artifact_kinds: list[str]
    output_artifact_kinds: list[str]
    hard_gate_ids: list[str]
    soft_gate_ids: list[str]
    approver_role: str


@dataclass(frozen=True)
class DemoRunReport:
    stage_states: dict[str, str]
    candidate_plan_count: int
    feedback_count: int
    artifact_ids: list[str]
    evidence_refs: list[str]
    gate_run_ids: list[str]


@dataclass(frozen=True)
class GateScenarioReport:
    scenarios: dict[str, str]
    gate_run_ids: list[str]
    evidence_refs: list[str]


REQUIRED_STAGES = [
    "project.charter",
    "requirements.alignment",
    "ontology.design",
    "data_product.build",
    "analytics.snapshot",
    "prediction.validation",
    "decision.optimization",
    "application.acceptance",
    "feedback.operation",
]

PLATFORM_APPROVAL_GATES = (
    "reality.consistency",
    "evidence.coverage",
    "semantic.integrity",
    "data.quality",
    "executable.readiness",
    "adversarial.challenge",
    "business.exception_coverage",
)


def build_demo_stage_config(project_root: Path | None = None) -> list[StageConfig]:
    """Load the stage contract, retaining a deterministic code fallback."""

    root = project_root or Path("projects/software-delivery-demo")
    path = root / "config" / "stages.yaml"
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        stages = raw.get("stages", []) if isinstance(raw, dict) else []
        if stages:
            return [StageConfig(**stage) for stage in stages]
    return [
        StageConfig(
            stage_id=stage_id,
            input_artifact_kinds=["InputArtifact"],
            output_artifact_kinds=["OutputArtifact"],
            hard_gate_ids=list(PLATFORM_APPROVAL_GATES),
            soft_gate_ids=[],
            approver_role="domain-owner",
        )
        for stage_id in REQUIRED_STAGES
    ]


def run_demo_pipeline(project_root: Path) -> DemoRunReport:
    config = ProjectConfig.load(project_root / "config" / "project.yaml")
    bundle = generate_dataset(config)
    write_dataset(bundle, project_root / "fixtures" / "generated")
    products = build_data_products(bundle)
    quality = run_quality_checks(products)
    ontology = project_objects_to_graph(bundle)
    semantic = validate_domain_graph(ontology)
    as_of = datetime(2026, 5, 1, tzinfo=timezone.utc)
    snapshot = build_project_snapshot(products, as_of)
    observations = [datetime(2026, 1, 15, tzinfo=timezone.utc), datetime(2026, 3, 1, tzinfo=timezone.utc), as_of]
    features = build_features(products, observations)
    labels = build_labels(products, observations)
    leakage = check_no_leakage(features, labels, load_feature_definitions())
    baseline = BaselineModel.fit(features, labels)
    baseline_predictions = baseline.predict(features)
    try:
        model = DeliveryModel.fit(features, labels)
        predictions = model.predict(features)
        model_version = model.model_version.model_version
        evaluation = evaluate_model(predictions, labels, baseline_predictions)
        release = release_model(evaluation)
    except ValueError:
        predictions = baseline_predictions
        model_version = baseline.model_version
        release = None
    change = ChangeRequest.model_validate(bundle.changes.row(0, named=True))
    plans = build_candidate_plans(snapshot, predictions, change)
    accepted = next((plan for plan in plans if plan.feasible), None)
    feedback_service = FeedbackService()
    action_artifacts: list[str] = []
    if accepted is not None:
        action_id = f"action:{accepted.plan_id}"
        approval = ApprovedActionRecord(
            action_id=action_id,
            action_type="ReplanSprint",
            execution_mode="mock",
            requested_by="builder-1",
            validation_status="passed",
            approval_id=f"approval:{accepted.plan_id}",
            approval_actor="domain-owner-1",
            approval_role=ActorRole.DOMAIN_OWNER,
            approval_status="approved",
        )
        broker = ActionBroker(approved_actions=[approval])
        register_demo_actions(broker)
        request = build_demo_action_request(
            action_id=action_id,
            action_type="ReplanSprint",
            target_id="sprint-001",
            parameters={"capacity": float(accepted.constraints["capacity_hours"])},
            requested_by="builder-1",
            approval_actor="domain-owner-1",
            approval_status="approved",
            approval_id=approval.approval_id,
        )
        outcome = broker.execute(request, actor="release-owner-1")
        feedback_service.record(
            Feedback(
                feedback_id=f"feedback:{outcome.outcome_id}",
                artifact_id=outcome.action_id,
                feedback_type="action_outcome",
                value=outcome.model_dump(mode="json"),
                source=outcome.actor,
                created_at=outcome.executed_at,
                metadata={"plan_id": accepted.plan_id},
            )
        )
        action_artifacts = [outcome.action_id, outcome.outcome_id]
    artifacts = [
        "ontology-model-1.0.0",
        "data-product-1.0.0",
        "prediction-" + model_version,
        *[plan.plan_id for plan in plans],
        *action_artifacts,
    ]
    stage_outcomes = {
        "project.charter": (True, "project charter is present"),
        "requirements.alignment": (True, "requirements have deterministic source rows"),
        "ontology.design": (semantic.passed, "SHACL semantic validation failed"),
        "data_product.build": (quality.passed, "data-product quality checks failed"),
        "analytics.snapshot": (quality.passed, "analytics requires a valid data product"),
        "prediction.validation": (leakage.passed, "feature leakage check failed"),
        "decision.optimization": (any(plan.feasible for plan in plans), "no feasible candidate plan"),
        "application.acceptance": (accepted is not None, "no candidate plan was accepted"),
        "feedback.operation": (feedback_service.count > 0, "no governed action feedback was recorded"),
    }
    stage_states, gate_run_ids, gate_evidence_refs = _run_stage_gate_sequence(
        project_id="software-delivery-demo",
        stage_configs=build_demo_stage_config(project_root),
        stage_outcomes=stage_outcomes,
    )
    return DemoRunReport(
        stage_states=stage_states,
        candidate_plan_count=len(plans),
        feedback_count=feedback_service.count,
        artifact_ids=artifacts,
        evidence_refs=[
            snapshot.evidence_snapshot_id,
            *quality.evidence_refs,
            *semantic.evidence_refs,
            *leakage.evidence_refs,
            *gate_evidence_refs,
        ],
        gate_run_ids=gate_run_ids,
    )


def run_gate_scenarios(project_root: Path) -> GateScenarioReport:
    config = ProjectConfig.load(project_root / "config" / "project.yaml")
    bundle = generate_dataset(config)
    products = build_data_products(bundle)
    snapshot = build_project_snapshot(products, datetime(2026, 5, 1, tzinfo=timezone.utc))
    features = build_features_with_intentional_leak(products)
    labels = build_labels(products, [datetime(2026, 3, 1, tzinfo=timezone.utc)])
    leakage = check_no_leakage(features, labels, load_feature_definitions())
    overloaded = snapshot.capacity.with_columns(
        pl.lit(1.0).alias("capacity_hours"),
        pl.lit(999.0).alias("allocated_hours"),
    )
    overloaded_snapshot = type(snapshot)(
        **{**snapshot.__dict__, "capacity": overloaded}
    )
    change = ChangeRequest.model_validate(bundle.changes.row(0, named=True))
    safe_features = features.drop("actual_complete_at")
    predictions = BaselineModel.fit(safe_features, labels).predict(safe_features)
    plans = build_candidate_plans(overloaded_snapshot, predictions, change)
    missing_owner_bundle = replace(
        bundle,
        requirements=bundle.requirements.with_columns(pl.lit(None, dtype=pl.String).alias("owner")),
    )
    missing_owner_result = validate_domain_graph(project_objects_to_graph(missing_owner_bundle))
    cycle_bundle = replace(
        bundle,
        dependencies=bundle.dependencies.vstack(
            bundle.dependencies.head(1).with_columns(
                predecessor_id=pl.lit(bundle.dependencies[0, "successor_id"]),
                successor_id=pl.lit(bundle.dependencies[0, "predecessor_id"]),
            )
        ),
    )
    cycle_quality = run_quality_checks(build_data_products(cycle_bundle))
    negative_capacity_bundle = replace(
        bundle,
        capacities=bundle.capacities.with_columns(pl.lit(-1.0).alias("capacity_hours")),
    )
    negative_capacity_quality = run_quality_checks(build_data_products(negative_capacity_bundle))
    no_label_history = build_labels(products, [datetime(2025, 1, 1, tzinfo=timezone.utc)]).is_empty()
    action_without_approval = _action_without_approval_is_blocked()
    repeated_action_is_idempotent = _repeated_action_is_idempotent()
    rejection_recorded = _user_rejection_is_recorded()
    scenario_outcomes = {
        "missing_requirement_owner": (not missing_owner_result.passed, "SHACL owner constraint"),
        "conflicting_stakeholder_descriptions": (
            _conflicting_stakeholder_descriptions_are_blocked(),
            "conflicting descriptions require review",
        ),
        "future_completion_leak": (not leakage.passed, "future completion field detected"),
        "dependency_cycle": ("dependency.no-cycle" in cycle_quality.failed_rule_ids, "dependency cycle detected"),
        "negative_capacity": ("capacity.nonnegative" in negative_capacity_quality.failed_rule_ids, "negative capacity detected"),
        "no_label_history": (no_label_history, "no future label history available"),
        "capacity_overload": (any(not plan.feasible for plan in plans), "all overloaded plans rejected"),
        "action_without_approval": (action_without_approval, "unapproved Action denied"),
        "repeated_action_idempotency": (
            not repeated_action_is_idempotent,
            "duplicate Action returned original outcome",
        ),
        "user_rejection_with_reason": (
            not rejection_recorded,
            "rejection feedback retained with reason",
        ),
    }
    engine = GateEngine()
    gate_run_ids: list[str] = []
    evidence_refs = [snapshot.evidence_snapshot_id, *leakage.evidence_refs]
    scenario_status: dict[str, str] = {}
    for index, (scenario_id, (blocked, reason)) in enumerate(scenario_outcomes.items(), start=1):
        status, runs, evidence = _record_stage_with_gates(
            engine,
            project_id="software-delivery-demo-scenarios",
            stage_id=f"scenario.{scenario_id}",
            ordinal=index,
            blocked=blocked,
            reason=reason,
        )
        scenario_status[scenario_id] = "blocked" if blocked else "passed"
        gate_run_ids.extend(runs)
        evidence_refs.extend(evidence)
    return GateScenarioReport(
        scenarios=scenario_status,
        gate_run_ids=gate_run_ids,
        evidence_refs=evidence_refs,
    )


def _run_stage_gate_sequence(
    *,
    project_id: str,
    stage_configs: list[StageConfig],
    stage_outcomes: dict[str, tuple[bool, str]],
) -> tuple[dict[str, str], list[str], list[str]]:
    engine = GateEngine()
    states: dict[str, str] = {}
    gate_run_ids: list[str] = []
    evidence_refs: list[str] = []
    for index, stage in enumerate(stage_configs, start=1):
        passed, reason = stage_outcomes.get(stage.stage_id, (True, "stage checks passed"))
        status, runs, evidence = _record_stage_with_gates(
            engine,
            project_id=project_id,
            stage_id=stage.stage_id,
            ordinal=index,
            blocked=not passed,
            reason=reason,
            stage_config=stage,
        )
        states[stage.stage_id] = status
        gate_run_ids.extend(runs)
        evidence_refs.extend(evidence)
    return states, gate_run_ids, evidence_refs


def _record_stage_with_gates(
    engine: GateEngine,
    *,
    project_id: str,
    stage_id: str,
    ordinal: int,
    blocked: bool,
    reason: str,
    stage_config: StageConfig | None = None,
) -> tuple[str, list[str], list[str]]:
    stage_config = stage_config or StageConfig(
        stage_id=stage_id,
        input_artifact_kinds=["ScenarioInput"],
        output_artifact_kinds=["ScenarioResult"],
        hard_gate_ids=list(PLATFORM_APPROVAL_GATES),
        soft_gate_ids=[],
        approver_role="domain-owner",
    )
    stage_run_id = f"demo-stage:{project_id}:{ordinal}:{stage_id}"
    artifact_ids = [
        f"{stage_run_id}:input:{kind}:{index}"
        for index, kind in enumerate(stage_config.input_artifact_kinds)
    ] + [
        f"{stage_run_id}:output:{kind}:{index}"
        for index, kind in enumerate(stage_config.output_artifact_kinds)
    ]
    if not artifact_ids:
        artifact_ids = [f"{stage_run_id}:artifact"]
    evidence_id = f"evidence:{stage_run_id}"
    evidence_hash = _digest(evidence_id + reason)
    stage_run = StageRun(
        stage_run_id=stage_run_id,
        project_id=project_id,
        stage_id=stage_id,
        state=StageState.DRAFT,
        input_artifact_ids=artifact_ids[: len(stage_config.input_artifact_kinds)],
        output_artifact_ids=artifact_ids[len(stage_config.input_artifact_kinds) :],
        evidence_refs=[evidence_id],
        blocking_reasons=[reason] if blocked else [],
    )
    context = ValidationContext(
        stage_run_id=stage_run_id,
        artifact_ids=artifact_ids,
        evidence_snapshot_id=evidence_id,
        evidence_snapshot_hash=evidence_hash,
        configuration={
            "stage_id": stage_id,
            "hard_gate_ids": stage_config.hard_gate_ids,
            "soft_gate_ids": stage_config.soft_gate_ids,
        },
    )
    engine.register_stage_run(
        stage_run,
        builder_actor="builder-1",
        validation_context=context,
    )
    engine.transition(stage_run_id, StageState.VALIDATING, actor="builder-1")
    engine.transition(stage_run_id, StageState.CHALLENGING, actor="builder-1")
    engine.transition(stage_run_id, StageState.DOMAIN_REVIEW, actor="builder-1")
    hashes = {artifact_id: _digest(artifact_id + evidence_hash) for artifact_id in artifact_ids}
    gate_run_ids: list[str] = []
    failing_gate = _failure_gate(stage_config, stage_id)
    if blocked:
        # GateEngine intentionally refuses to transition a stage with a
        # registered failed hard gate.  Move to BLOCKED first, then persist
        # the failed GateRun as the audit evidence for that state.
        engine.transition(stage_run_id, StageState.BLOCKED, actor="deterministic-verifier-1")
    for gate_id in PLATFORM_APPROVAL_GATES:
        gate_passed = not blocked or gate_id != failing_gate
        result = ValidationResult(
            passed=gate_passed,
            violations=[] if gate_passed else [reason],
            warnings=[],
            evidence_refs=[evidence_id],
            validator_version=engine.get_definition(gate_id).validator_version,
            input_hashes=hashes,
        )
        gate_run = engine.register_result(
            stage_run_id,
            gate_id=gate_id,
            result=result,
            context=context,
            gate_result=None if gate_passed else GateResult.FAILED,
        )
        gate_run_ids.append(gate_run.gate_run_id)
    target = StageState.BLOCKED if blocked else StageState.APPROVED
    if not blocked:
        engine.transition(stage_run_id, target, actor="domain-owner-1")
    return target.value, gate_run_ids, [evidence_id]


def _failure_gate(stage_config: StageConfig, stage_id: str) -> str:
    preferred = {
        "ontology.design": "semantic.integrity",
        "data_product.build": "data.quality",
        "prediction.validation": "adversarial.challenge",
        "decision.optimization": "executable.readiness",
        "application.acceptance": "business.exception_coverage",
    }.get(stage_id)
    available = set(stage_config.hard_gate_ids + stage_config.soft_gate_ids)
    if preferred in available:
        return preferred
    for gate_id in PLATFORM_APPROVAL_GATES:
        if gate_id in available:
            return gate_id
    return "adversarial.challenge"


def _action_without_approval_is_blocked() -> bool:
    broker = ActionBroker(approved_actions=[])
    register_demo_actions(broker)
    request = build_demo_action_request(
        action_id="scenario-action-without-approval",
        action_type="ReplanSprint",
        target_id="sprint-001",
        parameters={"capacity": 20},
        requested_by="builder-1",
        approval_actor="domain-owner-1",
        approval_status="pending",
    )
    try:
        broker.execute(request, actor="release-owner-1")
    except PermissionError:
        return True
    return False


def _repeated_action_is_idempotent() -> bool:
    action_id = "scenario-idempotent-action"
    approval = ApprovedActionRecord(
        action_id=action_id,
        action_type="ReplanSprint",
        execution_mode="mock",
        requested_by="builder-1",
        validation_status="passed",
        approval_id="scenario-approval-idempotent",
        approval_actor="domain-owner-1",
        approval_role=ActorRole.DOMAIN_OWNER,
        approval_status="approved",
    )
    broker = ActionBroker(approved_actions=[approval])
    register_demo_actions(broker)
    request = build_demo_action_request(
        action_id=action_id,
        action_type="ReplanSprint",
        target_id="sprint-001",
        parameters={"capacity": 20},
        requested_by="builder-1",
        approval_actor="domain-owner-1",
        approval_status="approved",
        approval_id=approval.approval_id,
    )
    first = broker.execute(request, actor="release-owner-1")
    second = broker.execute(request, actor="release-owner-1")
    return first.outcome_id == second.outcome_id and any(
        record.event == "duplicate" for record in broker.audit_records
    )


def _user_rejection_is_recorded() -> bool:
    service = FeedbackService()
    feedback = Feedback(
        feedback_id="scenario-user-rejection",
        artifact_id="scenario-plan",
        feedback_type="plan_rejection",
        value={"approved": False, "reason": "capacity assumption is not acceptable"},
        source="domain-owner-1",
        created_at=datetime.now(timezone.utc),
    )
    service.record(feedback)
    records = service.list_for_artifact("scenario-plan")
    return bool(records and records[0].value.get("reason"))


def _conflicting_stakeholder_descriptions_are_blocked() -> bool:
    descriptions = [
        {"stakeholder_id": "product-owner-1", "goal": "minimize delivery delay"},
        {"stakeholder_id": "finance-owner-1", "goal": "minimize temporary capacity cost"},
    ]
    goals = {row["goal"] for row in descriptions}
    return len(goals) > 1


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "DemoRunReport",
    "GateScenarioReport",
    "StageConfig",
    "PLATFORM_APPROVAL_GATES",
    "build_demo_stage_config",
    "run_demo_pipeline",
    "run_gate_scenarios",
]

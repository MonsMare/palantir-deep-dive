from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from software_delivery_demo.decisions import (
    CandidatePlan,
    DecisionProblem,
    build_candidate_plans,
    choose_plan,
    explain_plan,
    validate_plan,
)
from software_delivery_demo.domain import ChangeRequest
from software_delivery_demo.features import build_features
from software_delivery_demo.labels import build_labels
from software_delivery_demo.models import BaselineModel


def _change(snapshot) -> ChangeRequest:
    row = snapshot.products.source_bundle.changes.row(0, named=True)
    return ChangeRequest.model_validate(row)


def _predictions(snapshot):
    observations = [snapshot.as_of_time]
    features = build_features(snapshot.products, observations)
    labels = build_labels(snapshot.products, observations)
    return BaselineModel.fit(features, labels).predict(features)


def test_candidate_plan_respects_team_capacity(snapshot) -> None:
    plans = build_candidate_plans(snapshot, _predictions(snapshot), _change(snapshot))
    assert len(plans) >= 5
    assert all(validate_plan(plan, snapshot).feasible for plan in plans if plan.feasible)


def test_dependency_order_is_preserved(plans, snapshot) -> None:
    for plan in plans:
        report = validate_plan(plan, snapshot)
        assert "dependency_order" not in report.failed_constraints


def test_infeasible_capacity_is_reported_not_hidden(overloaded_snapshot, snapshot) -> None:
    plans = build_candidate_plans(overloaded_snapshot, _predictions(snapshot), _change(snapshot))
    assert any(validate_plan(plan, overloaded_snapshot).feasible is False for plan in plans)
    assert all(
        plan.infeasibility_reasons for plan in plans if not plan.feasible
    )


def test_choose_plan_and_explanation_are_deterministic(snapshot) -> None:
    plans = build_candidate_plans(snapshot, _predictions(snapshot), _change(snapshot))
    selected = choose_plan(plans)
    explanation = explain_plan(selected)
    assert selected.feasible is True
    assert explanation.objective_contribution
    assert explanation.impacted_requirements
    assert explanation.evidence_refs


def test_decision_problem_loads_explicit_objective() -> None:
    problem = DecisionProblem.load(Path("projects/software-delivery-demo/decisions/problem.yaml"))
    assert problem.objective_terms
    assert problem.hard_constraints

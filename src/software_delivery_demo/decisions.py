"""Transparent candidate-plan enumeration and hard-constraint validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
import polars as pl

from .analytics import ProjectSnapshot
from .domain import ChangeRequest


class DecisionProblem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variables: list[str]
    objective_terms: list[str]
    hard_constraints: list[str]

    @classmethod
    def load(cls, path: Path) -> "DecisionProblem":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)


class CandidatePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    objective_value: float
    changed_items: list[dict[str, Any]] = Field(default_factory=list)
    resource_delta: dict[str, float] = Field(default_factory=dict)
    completion_distribution: dict[str, float]
    constraints: dict[str, Any]
    assumptions: list[str] = Field(default_factory=list)
    feasible: bool
    infeasibility_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class FeasibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feasible: bool
    failed_constraints: list[str] = Field(default_factory=list)
    constraint_slack: dict[str, float] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class PlanExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    objective_contribution: dict[str, float]
    binding_constraints: list[str]
    slack: dict[str, float]
    impacted_requirements: list[str]
    predicted_dates: dict[str, str]
    evidence_refs: list[str]
    assumptions: list[str]


def build_candidate_plans(
    snapshot: ProjectSnapshot,
    prediction: pl.DataFrame,
    change: ChangeRequest,
) -> list[CandidatePlan]:
    if not isinstance(change, ChangeRequest):
        raise TypeError("change must be a ChangeRequest")
    problem = DecisionProblem.load(Path("projects/software-delivery-demo/decisions/problem.yaml"))
    capacity = _capacity_for_change(snapshot, change)
    added_hours = float(change.added_scope_hours)
    candidates = [
        ("reject-change", False, 0.0, "keep current commitment"),
        ("defer-low-priority", True, -min(added_hours, 8.0), "defer low-priority work"),
        ("split-scope", True, -min(added_hours * 0.4, 8.0), "split acceptance scope"),
        ("add-capacity", True, added_hours, "add temporary team capacity"),
        ("adjust-commitment", True, 0.0, "move commitment date"),
    ]
    p50 = _prediction_quantile(prediction, "p50_days", default=7.0)
    p80 = _prediction_quantile(prediction, "p80_days", default=p50 * 1.5)
    plans: list[CandidatePlan] = []
    for index, (kind, accepts, resource_delta, assumption) in enumerate(candidates, start=1):
        extra = added_hours if accepts else 0.0
        if kind == "defer-low-priority":
            extra = max(0.0, added_hours - 8.0)
        if kind == "split-scope":
            extra = max(0.0, added_hours * 0.6)
        if kind == "add-capacity":
            extra = max(0.0, added_hours - resource_delta)
        completion = {
            "p50_days": p50 + extra / 8.0,
            "p80_days": p80 + extra / 8.0,
        }
        objective = (
            completion["p50_days"] * (6 if change.priority >= 4 else 3)
            + max(0.0, extra) * 0.4
            + (2.0 if kind == "split-scope" else 0.0)
            + (1.0 if kind == "adjust-commitment" else 0.0)
            + (0.5 if kind == "defer-low-priority" else 0.0)
        )
        plan = CandidatePlan(
            plan_id=f"plan-{index:02d}-{kind}",
            objective_value=objective,
            changed_items=[
                {
                    "change_id": change.change_id,
                    "strategy": kind,
                    "accept_change": accepts,
                }
            ],
            resource_delta={"team_capacity_hours": resource_delta},
            completion_distribution=completion,
            constraints={
                "capacity_hours": capacity,
                "required_hours": extra,
                "dependency_order": True,
                "approved_items_immutable": True,
                "problem_variables": problem.variables,
            },
            assumptions=[assumption],
            feasible=True,
            evidence_refs=[snapshot.evidence_snapshot_id],
        )
        report = validate_plan(plan, snapshot)
        plans.append(
            plan.model_copy(
                update={
                    "feasible": report.feasible,
                    "infeasibility_reasons": report.failed_constraints,
                },
                deep=True,
            )
        )
    return plans


def validate_plan(plan: CandidatePlan, snapshot: ProjectSnapshot) -> FeasibilityReport:
    failed: list[str] = []
    capacity = float(plan.constraints.get("capacity_hours", 0.0))
    required = float(plan.constraints.get("required_hours", 0.0))
    capacity_slack = capacity - required
    if capacity_slack < 0:
        failed.append("capacity.no-over-allocation")
    if not bool(plan.constraints.get("dependency_order", False)):
        failed.append("dependency_order")
    for row in snapshot.products.source_bundle.work_items.iter_rows(named=True):
        if row["approved"] and any(
            change.get("work_item_id") == row["work_item_id"]
            and change.get("action") in {"defer", "split"}
            for change in plan.changed_items
        ):
            failed.append("approved_items_immutable")
        if row["status"] == "cancelled" and any(
            change.get("work_item_id") == row["work_item_id"]
            for change in plan.changed_items
        ):
            failed.append("cancelled_items_unscheduled")
    return FeasibilityReport(
        feasible=not failed,
        failed_constraints=list(dict.fromkeys(failed)),
        constraint_slack={"capacity_hours": capacity_slack},
        evidence_refs=[snapshot.evidence_snapshot_id],
    )


def choose_plan(plans: list[CandidatePlan]) -> CandidatePlan:
    feasible = [plan for plan in plans if plan.feasible]
    if not feasible:
        raise ValueError("no feasible candidate plan exists")
    return min(feasible, key=lambda plan: (plan.objective_value, plan.plan_id)).model_copy(deep=True)


def explain_plan(plan: CandidatePlan) -> PlanExplanation:
    return PlanExplanation(
        plan_id=plan.plan_id,
        objective_contribution={
            "delay_cost": plan.completion_distribution.get("p50_days", 0.0),
            "resource_cost": plan.resource_delta.get("team_capacity_hours", 0.0),
            "total": plan.objective_value,
        },
        binding_constraints=plan.infeasibility_reasons or [
            key for key, value in plan.constraints.items() if value is True
        ],
        slack={"capacity_hours": float(plan.constraints.get("capacity_hours", 0.0)) - float(plan.constraints.get("required_hours", 0.0))},
        impacted_requirements=[
            str(item.get("requirement_id") or item.get("change_id"))
            for item in plan.changed_items
        ],
        predicted_dates={
            "p50": f"+{plan.completion_distribution.get('p50_days', 0.0):.2f} days",
            "p80": f"+{plan.completion_distribution.get('p80_days', 0.0):.2f} days",
        },
        evidence_refs=list(plan.evidence_refs),
        assumptions=list(plan.assumptions),
    )


def _capacity_for_change(snapshot: ProjectSnapshot, change: ChangeRequest) -> float:
    if snapshot.capacity.is_empty():
        return 0.0
    return float(snapshot.capacity["capacity_hours"].sum() - snapshot.capacity["allocated_hours"].sum())


def _prediction_quantile(prediction: pl.DataFrame, column: str, default: float) -> float:
    if prediction.is_empty() or column not in prediction.columns:
        return default
    value = prediction[column].median()
    return default if value is None else float(value)


__all__ = [
    "CandidatePlan",
    "DecisionProblem",
    "FeasibilityReport",
    "PlanExplanation",
    "build_candidate_plans",
    "choose_plan",
    "explain_plan",
    "validate_plan",
]

"""Deterministic optimization adapters and domain problem factories."""

from __future__ import annotations

from itertools import product
from typing import Any
from hashlib import sha256
import json

from .contracts import (
    CandidatePlan,
    Constraint,
    DecisionVariable,
    Objective,
    OptimizationCertificate,
    OptimizationProblem,
    OptimizationResult,
)


class DeterministicEnumerator:
    """Enumerate small discrete domains with a replayable certificate."""

    def solve(self, problem: OptimizationProblem) -> OptimizationResult:
        if not isinstance(problem, OptimizationProblem):
            raise TypeError("problem must be an OptimizationProblem")
        combinations = 1
        for variable in problem.variables:
            combinations *= len(variable.domain)
        if combinations > problem.max_combinations:
            raise ValueError("optimization search space exceeds max_combinations")
        plans: list[CandidatePlan] = []
        for values in product(*(variable.domain for variable in problem.variables)):
            assignments = {
                variable.name: value
                for variable, value in zip(problem.variables, values, strict=True)
            }
            objective_values = {
                objective.objective_id: objective.constant
                + sum(objective.coefficients[name] * float(assignments[name]) for name in objective.coefficients)
                for objective in problem.objectives
            }
            violations: list[str] = []
            for constraint in problem.constraints:
                lhs = sum(constraint.coefficients[name] * float(assignments[name]) for name in constraint.coefficients)
                if not _satisfies(lhs, constraint.relation, constraint.rhs, constraint.tolerance):
                    violations.append(
                        f"{constraint.constraint_id}: {lhs} {constraint.relation} {constraint.rhs}"
                    )
            status = "feasible" if not any(
                item.startswith(f"{constraint.constraint_id}:")
                for constraint in problem.constraints
                if constraint.kind == "hard"
                for item in violations
            ) else "infeasible"
            plan_id = "plan:" + sha256(
                json.dumps(
                    {"problem": problem.problem_hash, "assignments": assignments},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()[:24]
            plans.append(
                CandidatePlan(
                    plan_id=plan_id,
                    problem_id=problem.problem_id,
                    assignments=assignments,
                    objective_values=objective_values,
                    constraint_status=status,
                    violations=tuple(violations),
                    ontology_release_id=problem.ontology_release_id,
                    ontology_version=problem.ontology_version,
                    feature_snapshot_id=problem.feature_snapshot_id,
                    prediction_ids=problem.prediction_ids,
                    evidence_refs=problem.evidence_refs,
                    solver_version=problem.solver_version,
                )
            )
        primary = problem.objectives[0]
        ordered = sorted(
            plans,
            key=lambda plan: (
                0 if plan.constraint_status == "feasible" else 1,
                plan.objective_values[primary.objective_id]
                if primary.direction == "minimize"
                else -plan.objective_values[primary.objective_id],
                plan.plan_id,
            ),
        )
        selected = next(
            (plan for plan in ordered if plan.constraint_status == "feasible"), None
        )
        status = "optimal" if selected is not None else "infeasible"
        certificate_values = {
            "problem_hash": problem.problem_hash,
            "selected_plan_id": selected.plan_id if selected else None,
            "candidate_count": len(ordered),
            "status": status,
            "solver_version": problem.solver_version,
        }
        certificate_hash = sha256(
            json.dumps(certificate_values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        certificate = OptimizationCertificate(
            certificate_id=f"certificate:{certificate_hash[:24]}",
            certificate_hash=certificate_hash,
            **certificate_values,
        )
        return OptimizationResult(
            plans=tuple(ordered), selected_plan=selected, certificate=certificate
        )


def _satisfies(lhs: float, relation: str, rhs: float, tolerance: float) -> bool:
    if relation == "le":
        return lhs <= rhs + tolerance
    if relation == "ge":
        return lhs >= rhs - tolerance
    return abs(lhs - rhs) <= tolerance


def build_supplier_delay_intervention_problem(
    *,
    ontology_release_id: str,
    feature_snapshot_id: str,
    prediction_ids: tuple[str, ...],
    evidence_refs: tuple[str, ...],
) -> OptimizationProblem:
    """Build a small governed intervention problem for supplier delay risk."""

    return OptimizationProblem(
        problem_id="supplier-delay-intervention",
        ontology_release_id=ontology_release_id,
        ontology_version="0.1.0",
        feature_snapshot_id=feature_snapshot_id,
        prediction_ids=prediction_ids,
        evidence_refs=evidence_refs,
        variables=(DecisionVariable(name="intervention_level", value_type="integer", domain=(0, 1, 2)),),
        objectives=(Objective(objective_id="minimize_intervention_cost", direction="minimize", coefficients={"intervention_level": 10.0}),),
        constraints=(Constraint(constraint_id="minimum_risk_response", kind="hard", coefficients={"intervention_level": -1.0}, relation="le", rhs=-1.0),),
    )


def build_software_delivery_plan_problem(
    *,
    ontology_release_id: str,
    feature_snapshot_id: str,
    prediction_ids: tuple[str, ...],
    evidence_refs: tuple[str, ...],
) -> OptimizationProblem:
    """Build a sprint assignment problem with a capacity hard constraint."""

    return OptimizationProblem(
        problem_id="software-delivery-sprint-plan",
        ontology_release_id=ontology_release_id,
        ontology_version="0.1.0",
        feature_snapshot_id=feature_snapshot_id,
        prediction_ids=prediction_ids,
        evidence_refs=evidence_refs,
        variables=(DecisionVariable(name="sprint_offset", value_type="integer", domain=(0, 1, 2)),),
        objectives=(Objective(objective_id="minimize_delay", direction="minimize", coefficients={"sprint_offset": 1.0}),),
        constraints=(Constraint(constraint_id="capacity_available", kind="hard", coefficients={"sprint_offset": 1.0}, relation="le", rhs=2.0),),
    )


__all__ = [
    "DeterministicEnumerator",
    "build_software_delivery_plan_problem",
    "build_supplier_delay_intervention_problem",
]

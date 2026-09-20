from __future__ import annotations

import pytest

from aifde.optimization.contracts import (
    Constraint,
    DecisionVariable,
    Objective,
    OptimizationProblem,
)
from aifde.optimization.solvers import DeterministicEnumerator


def _problem() -> OptimizationProblem:
    return OptimizationProblem(
        problem_id="supplier-intervention",
        ontology_release_id="ontology-release:1",
        ontology_version="0.1.0",
        feature_snapshot_id="feature-snapshot:1",
        prediction_ids=("prediction:PO-001",),
        evidence_refs=("evidence:delay-signal",),
        variables=(
            DecisionVariable(
                name="expedite_level",
                value_type="integer",
                domain=(0, 1, 2),
            ),
        ),
        objectives=(
            Objective(
                objective_id="minimize_cost",
                direction="minimize",
                coefficients={"expedite_level": 10.0},
            ),
        ),
        constraints=(
            Constraint(
                constraint_id="meet_risk_threshold",
                kind="hard",
                coefficients={"expedite_level": -1.0},
                relation="le",
                rhs=-1.0,
            ),
        ),
    )


def test_problem_requires_objective_variable_and_hard_constraint() -> None:
    with pytest.raises(ValueError, match="variable"):
        OptimizationProblem(
            problem_id="bad",
            ontology_release_id="release",
            ontology_version="1",
            feature_snapshot_id="snapshot",
            prediction_ids=("prediction",),
            evidence_refs=("evidence",),
            variables=(),
            objectives=(_problem().objectives[0],),
            constraints=(_problem().constraints[0],),
        )
    with pytest.raises(ValueError, match="objective"):
        OptimizationProblem(
            problem_id="bad",
            ontology_release_id="release",
            ontology_version="1",
            feature_snapshot_id="snapshot",
            prediction_ids=("prediction",),
            evidence_refs=("evidence",),
            variables=(_problem().variables[0],),
            objectives=(),
            constraints=(_problem().constraints[0],),
        )
    with pytest.raises(ValueError, match="hard constraint"):
        OptimizationProblem(
            problem_id="bad",
            ontology_release_id="release",
            ontology_version="1",
            feature_snapshot_id="snapshot",
            prediction_ids=("prediction",),
            evidence_refs=("evidence",),
            variables=(_problem().variables[0],),
            objectives=(_problem().objectives[0],),
            constraints=(),
        )


def test_deterministic_solver_selects_feasible_plan_and_is_replayable() -> None:
    solver = DeterministicEnumerator()

    first = solver.solve(_problem())
    second = solver.solve(_problem())

    assert first.selected_plan is not None
    assert first.selected_plan.assignments == {"expedite_level": 1}
    assert first.selected_plan.constraint_status == "feasible"
    assert first.certificate.certificate_hash == second.certificate.certificate_hash
    assert [item.plan_id for item in first.plans] == [item.plan_id for item in second.plans]
    assert first.certificate.selected_plan_id == first.selected_plan.plan_id


def test_infeasible_problem_cannot_enter_approval() -> None:
    problem = _problem().model_copy(
        update={
            "constraints": (
                Constraint(
                    constraint_id="impossible",
                    kind="hard",
                    coefficients={"expedite_level": 1.0},
                    relation="le",
                    rhs=-1.0,
                ),
            )
        }
    )
    result = DeterministicEnumerator().solve(problem)

    assert result.selected_plan is None
    assert result.certificate.status == "infeasible"
    with pytest.raises(ValueError, match="feasible"):
        result.require_approvable()


def test_optimizer_rejects_cross_context_prediction_at_problem_boundary() -> None:
    with pytest.raises(ValueError, match="prediction_ids"):
        _problem().model_copy(update={"prediction_ids": ()})

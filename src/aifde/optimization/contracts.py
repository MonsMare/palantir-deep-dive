"""Typed optimization problem, candidate, and certificate contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _refs(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{name} must be a sequence")
    result = tuple(_text(item, name) for item in value)
    if not result:
        raise ValueError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicates")
    return result


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        values = self.model_dump(mode="python")
        if deep:
            import copy

            values = copy.deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)


class DecisionVariable(_FrozenModel):
    name: str
    value_type: Literal["integer", "number", "string", "boolean"]
    domain: tuple[Any, ...]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _text(value, "name")

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, value: Any) -> tuple[Any, ...]:
        if isinstance(value, (str, bytes)):
            raise TypeError("variable domain must be a sequence")
        result = tuple(value)
        if not result:
            raise ValueError("variable domain must not be empty")
        if len(result) != len({_canonical(value) for value in result}):
            raise ValueError("variable domain must not contain duplicates")
        return result


class Objective(_FrozenModel):
    objective_id: str
    direction: Literal["minimize", "maximize"]
    coefficients: dict[str, float]
    constant: float = 0.0

    @field_validator("objective_id")
    @classmethod
    def validate_objective_id(cls, value: str) -> str:
        return _text(value, "objective_id")

    @field_validator("coefficients", mode="before")
    @classmethod
    def normalize_coefficients(cls, value: Any) -> dict[str, float]:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("objective coefficients must not be empty")
        return {str(key): float(item) for key, item in value.items()}


class Constraint(_FrozenModel):
    constraint_id: str
    kind: Literal["hard", "soft"]
    coefficients: dict[str, float]
    relation: Literal["le", "ge", "eq"]
    rhs: float
    tolerance: float = Field(default=1e-9, ge=0.0)

    @field_validator("constraint_id")
    @classmethod
    def validate_constraint_id(cls, value: str) -> str:
        return _text(value, "constraint_id")

    @field_validator("coefficients", mode="before")
    @classmethod
    def normalize_constraint_coefficients(cls, value: Any) -> dict[str, float]:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("constraint coefficients must not be empty")
        return {str(key): float(item) for key, item in value.items()}


class OptimizationProblem(_FrozenModel):
    problem_id: str
    ontology_release_id: str
    ontology_version: str
    feature_snapshot_id: str
    prediction_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    variables: tuple[DecisionVariable, ...]
    objectives: tuple[Objective, ...]
    constraints: tuple[Constraint, ...]
    solver_version: str = "deterministic-enumerator-v1"
    max_combinations: int = Field(default=10_000, gt=0)

    @field_validator(
        "problem_id",
        "ontology_release_id",
        "ontology_version",
        "feature_snapshot_id",
        "solver_version",
    )
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @field_validator("prediction_ids", "evidence_refs", mode="before")
    @classmethod
    def validate_refs(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _refs(value, info.field_name)

    @field_validator("variables", "objectives", "constraints", mode="before")
    @classmethod
    def normalize_collections(cls, value: Any, info: Any) -> tuple[Any, ...]:
        if value is None:
            return ()
        if isinstance(value, (str, bytes)):
            raise TypeError(f"{info.field_name} must be a sequence")
        return tuple(value)

    @model_validator(mode="after")
    def validate_problem(self) -> Self:
        if not self.variables:
            raise ValueError("optimization problem requires at least one variable")
        if not self.objectives:
            raise ValueError("optimization problem requires at least one objective")
        if not self.constraints or not any(item.kind == "hard" for item in self.constraints):
            raise ValueError("optimization problem requires at least one hard constraint")
        variable_names = {item.name for item in self.variables}
        if len(variable_names) != len(self.variables):
            raise ValueError("optimization variable names must be unique")
        objective_ids = {item.objective_id for item in self.objectives}
        if len(objective_ids) != len(self.objectives):
            raise ValueError("optimization objective IDs must be unique")
        constraint_ids = {item.constraint_id for item in self.constraints}
        if len(constraint_ids) != len(self.constraints):
            raise ValueError("optimization constraint IDs must be unique")
        for item in (*self.objectives, *self.constraints):
            if not set(item.coefficients).issubset(variable_names):
                raise ValueError("optimization expression references unknown variable")
        return self

    @property
    def problem_hash(self) -> str:
        return sha256(
            json.dumps(
                self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()


class CandidatePlan(_FrozenModel):
    plan_id: str
    problem_id: str
    assignments: dict[str, Any]
    objective_values: dict[str, float]
    constraint_status: Literal["feasible", "infeasible"]
    violations: tuple[str, ...] = ()
    ontology_release_id: str
    ontology_version: str
    feature_snapshot_id: str
    prediction_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    solver_version: str


class OptimizationCertificate(_FrozenModel):
    certificate_id: str
    problem_hash: str
    selected_plan_id: str | None
    candidate_count: int = Field(ge=0)
    status: Literal["optimal", "infeasible"]
    solver_version: str
    certificate_hash: str


class OptimizationResult(_FrozenModel):
    plans: tuple[CandidatePlan, ...]
    selected_plan: CandidatePlan | None
    certificate: OptimizationCertificate

    def require_approvable(self) -> CandidatePlan:
        if self.selected_plan is None or self.certificate.status != "optimal":
            raise ValueError("optimization result has no feasible plan")
        if self.selected_plan.constraint_status != "feasible":
            raise ValueError("selected optimization plan is not feasible")
        return self.selected_plan


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "CandidatePlan",
    "Constraint",
    "DecisionVariable",
    "Objective",
    "OptimizationCertificate",
    "OptimizationProblem",
    "OptimizationResult",
]

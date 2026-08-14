"""Typed domain-agent roles and model routing policy."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentRole(str, Enum):
    DECISION_ANALYST = "decision-analyst"
    WORKFLOW_ANALYST = "workflow-analyst"
    ONTOLOGY_ENGINEER = "ontology-engineer"
    DATA_PRODUCT_ENGINEER = "data-product-engineer"
    MODEL_ENGINEER = "model-engineer"
    DECISION_AGENT = "decision-agent"
    CHALLENGER = "challenger"
    RELEASE_AGENT = "release-agent"


class ModelTier(str, Enum):
    DETERMINISTIC = "deterministic"
    FAST = "fast"
    LARGE = "large"


class RoleSpec(BaseModel):
    """The capabilities and default model tier of one typed role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: AgentRole
    model_tier: ModelTier
    can_propose: bool = True
    can_challenge: bool = False
    independent_context: bool = False
    allowed_output_kinds: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("allowed_output_kinds")
    @classmethod
    def validate_output_kinds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("allowed_output_kinds must contain non-empty strings")
        return tuple(value)


class ModelRoute(BaseModel):
    """A provider-independent route selected before an agent is invoked."""

    model_id: str
    tier: ModelTier
    task_kind: str
    write_capability: bool = False

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("model_id", "task_kind")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("model route identity must not be blank")
        return value


_ROLE_SPECS: Mapping[AgentRole, RoleSpec] = MappingProxyType(
    {
        AgentRole.DECISION_ANALYST: RoleSpec(
            role=AgentRole.DECISION_ANALYST,
            model_tier=ModelTier.LARGE,
            allowed_output_kinds=("DecisionContract", "DecisionAnalysis"),
        ),
        AgentRole.WORKFLOW_ANALYST: RoleSpec(
            role=AgentRole.WORKFLOW_ANALYST,
            model_tier=ModelTier.LARGE,
            allowed_output_kinds=("WorkflowObservation", "RequirementsSpecification"),
        ),
        AgentRole.ONTOLOGY_ENGINEER: RoleSpec(
            role=AgentRole.ONTOLOGY_ENGINEER,
            model_tier=ModelTier.LARGE,
            allowed_output_kinds=("OntologyModel", "OntologyIR"),
        ),
        AgentRole.DATA_PRODUCT_ENGINEER: RoleSpec(
            role=AgentRole.DATA_PRODUCT_ENGINEER,
            model_tier=ModelTier.FAST,
            allowed_output_kinds=("DataProduct", "DataRegistration"),
        ),
        AgentRole.MODEL_ENGINEER: RoleSpec(
            role=AgentRole.MODEL_ENGINEER,
            model_tier=ModelTier.LARGE,
            allowed_output_kinds=("FeatureDefinition", "ModelPackage"),
        ),
        AgentRole.DECISION_AGENT: RoleSpec(
            role=AgentRole.DECISION_AGENT,
            model_tier=ModelTier.LARGE,
            allowed_output_kinds=("OptimizationPlan", "DecisionPolicy"),
        ),
        AgentRole.CHALLENGER: RoleSpec(
            role=AgentRole.CHALLENGER,
            model_tier=ModelTier.LARGE,
            can_challenge=True,
            independent_context=True,
            allowed_output_kinds=("ChallengeReport",),
        ),
        AgentRole.RELEASE_AGENT: RoleSpec(
            role=AgentRole.RELEASE_AGENT,
            model_tier=ModelTier.DETERMINISTIC,
            allowed_output_kinds=("ReleaseCandidate",),
        ),
    }
)


class ModelRouter:
    """Select a model tier without granting that model write authority."""

    def __init__(self, overrides: Mapping[AgentRole | str, ModelRoute] | None = None) -> None:
        routes: dict[AgentRole, ModelRoute] = {}
        for role, spec in _ROLE_SPECS.items():
            routes[role] = ModelRoute(
                model_id=f"aifde-{spec.model_tier.value}",
                tier=spec.model_tier,
                task_kind="default",
                write_capability=False,
            )
        for role, route in (overrides or {}).items():
            normalized = role if isinstance(role, AgentRole) else AgentRole(role)
            routes[normalized] = route
        self._routes = MappingProxyType(routes)

    def route(self, role: AgentRole, task_kind: str) -> ModelRoute:
        role = role if isinstance(role, AgentRole) else AgentRole(role)
        if role not in self._routes:
            raise KeyError(f"unknown agent role: {role}")
        base = self._routes[role]
        return base.model_copy(update={"task_kind": task_kind})

    @staticmethod
    def spec(role: AgentRole) -> RoleSpec:
        role = role if isinstance(role, AgentRole) else AgentRole(role)
        return _ROLE_SPECS[role]


__all__ = [
    "AgentRole",
    "ModelRoute",
    "ModelRouter",
    "ModelTier",
    "RoleSpec",
]

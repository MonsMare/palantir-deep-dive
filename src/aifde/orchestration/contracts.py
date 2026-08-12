"""Typed contracts exchanged by orchestration agents."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


@runtime_checkable
class ToolGatewayProtocol(Protocol):
    """Minimal protocol an orchestration agent needs from a tool gateway."""

    def issue_context(self, **kwargs: Any) -> Any:
        """Issue a trusted tool context."""

    def call(self, tool_id: str, context: Any, payload: dict[str, Any]) -> Any:
        """Invoke a tool through policy and audit."""


class _StrictContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
    )


class TaskContract(_StrictContractModel):
    """A bounded instruction set for a single stage run."""

    task_id: str
    objective: str
    stage_id: str
    actor: str | None = None
    allowed_evidence: list[str]
    required_output: list[str]
    forbidden_assumptions: list[str]
    acceptance_tests: list[str]
    escalation_conditions: list[str]

    @field_validator("task_id", "objective", "stage_id")
    @classmethod
    def reject_blank_required_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator(
        "allowed_evidence",
        "required_output",
        "forbidden_assumptions",
        "acceptance_tests",
        "escalation_conditions",
    )
    @classmethod
    def reject_blank_list_items(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("list items must be non-empty strings")
        return list(value)


class AgentContext(_StrictContractModel):
    """Runtime context shared with agents for a stage run."""

    project_id: str
    stage_id: str
    evidence_snapshot_id: str
    artifact_ids: list[str]
    tool_gateway: ToolGatewayProtocol

    @field_validator("project_id", "stage_id", "evidence_snapshot_id")
    @classmethod
    def reject_blank_required_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("artifact_ids")
    @classmethod
    def reject_blank_artifact_ids(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("artifact_ids must contain non-empty strings")
        return list(value)


class AgentProposal(_StrictContractModel):
    """Builder output proposal before independent challenge and gate review."""

    artifact_ids: list[str]
    evidence_refs: list[str]
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifact_payloads: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("artifact_ids", "evidence_refs", "open_questions", "assumptions", "warnings")
    @classmethod
    def reject_blank_references(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("list items must be non-empty strings")
        return list(value)


class Finding(_StrictContractModel):
    """A challenger finding that must be resolved or escalated."""

    code: str
    message: str
    artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("code", "message")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("artifact_id")
    @classmethod
    def reject_blank_optional_artifact_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("artifact_id must not be blank")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def reject_blank_evidence_refs(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("evidence_refs must contain non-empty strings")
        return list(value)


class ChallengeReport(_StrictContractModel):
    """Independent challenge result for proposed artifacts."""

    result: Literal["passed", "failed"]
    findings: list[Finding] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    required_remediation: list[str] = Field(default_factory=list)

    @field_validator("evidence_refs", "required_remediation")
    @classmethod
    def reject_blank_list_items(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("list items must be non-empty strings")
        return list(value)

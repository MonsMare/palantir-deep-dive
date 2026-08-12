"""Typed protocol shared by all tools and the Tool Gateway."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.policy.capabilities import Capability, ToolContext


class ToolResult(BaseModel):
    """The only result shape a tool may return through the gateway."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    status: str
    artifact_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    audit_id: str = Field(default_factory=lambda: str(uuid4()))

    @field_validator("status", "audit_id")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()

    @field_validator("artifact_ids", "evidence_refs")
    @classmethod
    def reject_blank_references(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("references must contain non-empty strings")
        return [item.strip() for item in value]


@runtime_checkable
class Tool(Protocol):
    """A tool has no database surface: it receives context and returns a result."""

    tool_id: str
    required_capabilities: frozenset[Capability]
    allowed_stage_ids: frozenset[str]

    def call(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        """Perform a bounded operation using only the supplied request context."""
        ...


__all__ = ["Capability", "Tool", "ToolContext", "ToolResult"]

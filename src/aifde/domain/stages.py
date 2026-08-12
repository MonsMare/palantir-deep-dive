"""Stage lifecycle domain contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class StageState(str, Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    CHALLENGING = "challenging"
    DOMAIN_REVIEW = "domain_review"
    APPROVED = "approved"
    RELEASE_CANDIDATE = "release_candidate"
    RELEASED = "released"
    REMEDIATION = "remediation"
    BLOCKED = "blocked"


class StageRun(BaseModel):
    """Traceable state for one project stage execution."""

    stage_run_id: str
    project_id: str
    stage_id: str
    state: StageState = StageState.DRAFT
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)

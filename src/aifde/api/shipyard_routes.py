"""FastAPI HTTP boundary for the governed Shipyard Workbench service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from aifde.domain.artifacts import Artifact
from aifde.shipyard.contracts import (
    AgentProposal,
    AuditEvent,
    DecisionCase,
    GateReviewSnapshot,
    ProjectWorkspace,
    ReleaseCandidate,
)
from aifde.shipyard.identity import Principal, UnauthorizedError
from aifde.shipyard.service import (
    RecordNotFoundError,
    ReleaseBlockedError,
    ShipyardApplicationService,
    StaleRevisionError,
)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceCreateRequest(_StrictRequest):
    workspace_id: str
    project_id: str
    name: str
    domain_pack: str
    current_phase: str = "intake"


class DecisionCaseCreateRequest(_StrictRequest):
    case_id: str
    name: str
    objective: str
    decision_owner: str
    users: list[str]
    trigger: str
    inputs: list[str]
    actions: list[str]
    constraints: list[str] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    baseline: str
    success_definition: str
    failure_definition: str
    status: Literal["draft", "active", "completed", "archived"] = "draft"


class ProposalCreateRequest(_StrictRequest):
    proposal_id: str
    task_packet_id: str
    proposed_changes: dict[str, JsonValue]
    affected_artifact_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    validation_results: list[JsonValue] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_step: str = "request human review"
    base_revision: int | None = Field(default=None, ge=1)


class ProposalDecisionRequest(_StrictRequest):
    decision: Literal["accept", "reject", "return"]


class GateReviewCreateRequest(_StrictRequest):
    gate_run_id: str
    revision: int = Field(default=1, ge=1)
    gate_id: str
    severity: Literal["hard", "soft"]
    status: Literal["pending", "passed", "failed", "blocked"] = "pending"
    artifact_hashes: dict[str, str]
    artifact_versions: dict[str, str] = Field(default_factory=dict)
    source_snapshot_id: str = ""
    source_snapshot_hash: str = ""
    input_snapshot_hash: str = ""
    validator_version: str
    definition_fingerprint: str = ""
    outcome_attestation: str = ""
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    stale: bool = False
    created_at: datetime | None = None


class ReleaseCandidateCreateRequest(_StrictRequest):
    artifact_ids: list[str]
    gate_run_ids: list[str]


class SnapshotResponse(_StrictRequest):
    workspace: ProjectWorkspace
    decision_cases: list[DecisionCase]
    artifacts: list[Artifact]
    proposals: list[AgentProposal]
    gate_reviews: list[GateReviewSnapshot]
    release_candidates: list[ReleaseCandidate]
    audit_events: list[AuditEvent]


_T = TypeVar("_T")


def _jsonable(value: Any) -> Any:
    """Convert only public Pydantic values into JSON-safe response data."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (RecordNotFoundError, KeyError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, UnauthorizedError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (StaleRevisionError, ReleaseBlockedError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (ValidationError, TypeError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


def _service_call(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except (RecordNotFoundError, KeyError, UnauthorizedError) as exc:
        raise _http_error(exc) from exc
    except (StaleRevisionError, ReleaseBlockedError) as exc:
        raise _http_error(exc) from exc
    except (ValidationError, TypeError, ValueError) as exc:
        raise _http_error(exc) from exc


def identity_dependency(
    service: ShipyardApplicationService,
) -> Callable[..., Principal]:
    """Build the request dependency that resolves the trusted identity header."""

    def resolve_identity(
        identity_header: str | None = Header(
            default=None, alias="X-Shipyard-Identity"
        ),
    ) -> Principal:
        if identity_header is None or not identity_header.strip():
            raise HTTPException(
                status_code=401,
                detail="X-Shipyard-Identity header is required",
            )
        try:
            principal = service.identity_provider.resolve(
                {"X-Shipyard-Identity": identity_header}
            )
        except UnauthorizedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if not isinstance(principal, Principal):
            raise HTTPException(status_code=403, detail="identity provider returned an invalid Principal")
        return principal

    return resolve_identity


def build_router(service: ShipyardApplicationService) -> APIRouter:
    """Build the Workbench routes around the supplied application service."""

    router = APIRouter(tags=["shipyard-workbench"])
    identity = identity_dependency(service)

    @router.post(
        "/workspaces",
        response_model=ProjectWorkspace,
        status_code=201,
    )
    def create_workspace(
        payload: WorkspaceCreateRequest,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        workspace = _service_call(
            lambda: service.create_workspace(payload.model_dump(mode="python"), principal)
        )
        return _jsonable(workspace)

    @router.get("/workspaces", response_model=list[ProjectWorkspace])
    def list_workspaces(
        principal: Principal = Depends(identity),
    ) -> list[dict[str, Any]]:
        del principal
        workspaces = _service_call(service.list_workspaces)
        return [_jsonable(workspace) for workspace in workspaces]

    @router.get(
        "/workspaces/{workspace_id}",
        response_model=ProjectWorkspace,
    )
    def get_workspace(
        workspace_id: str,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        del principal
        workspace = _service_call(lambda: service.get_workspace(workspace_id))
        return _jsonable(workspace)

    @router.post(
        "/workspaces/{workspace_id}/decision-cases",
        response_model=DecisionCase,
        status_code=201,
    )
    def create_decision_case(
        workspace_id: str,
        payload: DecisionCaseCreateRequest,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        values = payload.model_dump(mode="python")
        values["workspace_id"] = workspace_id
        decision_case = _service_call(
            lambda: service.create_decision_case(workspace_id, values, principal)
        )
        return _jsonable(decision_case)

    @router.get(
        "/workspaces/{workspace_id}/decision-cases",
        response_model=list[DecisionCase],
    )
    def list_decision_cases(
        workspace_id: str,
        principal: Principal = Depends(identity),
    ) -> list[dict[str, Any]]:
        del principal
        decision_cases = _service_call(
            lambda: service.list_decision_cases(workspace_id)
        )
        return [_jsonable(decision_case) for decision_case in decision_cases]

    @router.post(
        "/workspaces/{workspace_id}/proposals",
        response_model=AgentProposal,
        status_code=201,
    )
    def submit_proposal(
        workspace_id: str,
        payload: ProposalCreateRequest,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        values = payload.model_dump(mode="python", exclude_none=True)
        values["workspace_id"] = workspace_id
        proposal = _service_call(
            lambda: service.submit_agent_proposal(workspace_id, values, principal)
        )
        return _jsonable(proposal)

    @router.post(
        "/proposals/{proposal_id}/decision",
        response_model=AgentProposal,
    )
    def decide_proposal(
        proposal_id: str,
        payload: ProposalDecisionRequest,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        proposal = _service_call(
            lambda: service.decide_proposal(proposal_id, payload.decision, principal)
        )
        return _jsonable(proposal)

    @router.post(
        "/workspaces/{workspace_id}/gate-reviews",
        response_model=GateReviewSnapshot,
        status_code=201,
    )
    def record_gate_review(
        workspace_id: str,
        payload: GateReviewCreateRequest,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        values = payload.model_dump(mode="python", exclude_none=True)
        values["workspace_id"] = workspace_id
        gate_review = _service_call(
            lambda: service.record_gate_review(
                GateReviewSnapshot.model_validate(values), principal
            )
        )
        return _jsonable(gate_review)

    @router.post(
        "/workspaces/{workspace_id}/release-candidates",
        response_model=ReleaseCandidate,
        status_code=201,
    )
    def create_release_candidate(
        workspace_id: str,
        payload: ReleaseCandidateCreateRequest,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        candidate = _service_call(
            lambda: service.create_release_candidate(
                workspace_id,
                payload.artifact_ids,
                payload.gate_run_ids,
                principal,
            )
        )
        return _jsonable(candidate)

    @router.get(
        "/workspaces/{workspace_id}/snapshot",
        response_model=SnapshotResponse,
    )
    def get_workspace_snapshot(
        workspace_id: str,
        principal: Principal = Depends(identity),
    ) -> dict[str, Any]:
        del principal
        snapshot = _service_call(lambda: service.get_workspace_snapshot(workspace_id))
        return _jsonable(snapshot)

    return router


__all__ = [
    "DecisionCaseCreateRequest",
    "GateReviewCreateRequest",
    "ProposalCreateRequest",
    "ProposalDecisionRequest",
    "ReleaseCandidateCreateRequest",
    "SnapshotResponse",
    "WorkspaceCreateRequest",
    "build_router",
    "identity_dependency",
]

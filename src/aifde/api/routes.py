"""Route registration for the AI FDE project cockpit."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, JsonValue, ValidationError

from aifde.domain.actions import ActionRequest
from aifde.domain.stages import StageState
from aifde.gates.engine import TransitionBlocked
from aifde.ontology.computation import GovernedActionRequest
from aifde.policy.capabilities import PolicyEngine


def _model_config(extra: str = "ignore") -> dict[str, Any]:
    return {"extra": extra}


class StageSummary(BaseModel):
    stage_id: str
    state: str
    blocking_gate_ids: list[str] = Field(default_factory=list)
    pending_approval_ids: list[str] = Field(default_factory=list)
    latest_run_id: str | None = None

    model_config = _model_config()


class ArtifactSummary(BaseModel):
    artifact_id: str
    kind: str
    version: str
    status: str
    content_hash: str
    updated_at: str

    model_config = _model_config()


class GateSummary(BaseModel):
    gate_id: str
    severity: str
    status: str
    stage_id: str | None = None
    latest_run_id: str | None = None

    model_config = _model_config()


class StageRunCreateRequest(BaseModel):
    stage_id: str
    actor: str

    model_config = _model_config("forbid")


class StageRunResponse(BaseModel):
    stage_run_id: str
    project_id: str
    stage_id: str
    actor: str | None = None
    state: str

    model_config = _model_config()


class TransitionRequest(BaseModel):
    target: str
    actor: str

    model_config = _model_config("forbid")


class TransitionResponse(BaseModel):
    stage_run_id: str
    from_state: str | None = None
    to_state: str
    actor: str
    gate_run_ids: list[str] = Field(default_factory=list)

    model_config = _model_config()


class ActionExecuteRequest(BaseModel):
    """An execution envelope for an already-governed domain request.

    An ungoverned proposal is a different concept and cannot be promoted by
    this API.  The nested domain request is fully validated before this route
    runs, while ActionBroker remains authoritative for policy and approval.
    """

    request: ActionRequest
    actor: str

    model_config = _model_config("forbid")


class ActionOutcomeResponse(BaseModel):
    outcome_id: str
    action_id: str
    status: str | None = None

    model_config = _model_config()


class GovernedActionExecuteRequest(BaseModel):
    request: GovernedActionRequest
    actor: str

    model_config = _model_config("forbid")


class GovernedActionResponse(BaseModel):
    action_id: str
    external_ref: str
    outcome_id: str
    reconciliation_status: str
    status: str

    model_config = _model_config()


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _ensure_project(registry: Any, project_id: str) -> Any:
    try:
        return registry.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown project") from exc


def _build_action_request(payload: ActionExecuteRequest) -> ActionRequest:
    """Build only a fully validated domain request; never downgrade its type."""

    try:
        return ActionRequest.model_validate(
            payload.request.model_dump(mode="python")
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def build_router(
    *,
    registry: Any,
    gate_engine: Any,
    stage_runner: Any,
    action_broker: Any,
    policy: PolicyEngine | None = None,
    governed_action_broker: Any | None = None,
) -> APIRouter:
    """Return the route collection backed by the supplied domain services."""

    router = APIRouter()
    trusted_policy = policy or PolicyEngine()

    def resolve_transition_actor(actor: str, actor_header: str | None) -> str:
        if not actor_header:
            raise HTTPException(status_code=403, detail="trusted actor header is required")
        if actor_header != actor:
            raise HTTPException(status_code=403, detail="actor header does not match request actor")
        if trusted_policy.actor_binding(actor_header) is None:
            raise HTTPException(status_code=403, detail="unknown actor")
        return actor_header

    @router.get("/projects/{project_id}/stages", response_model=list[StageSummary])
    def list_project_stages(project_id: str) -> list[StageSummary]:
        _ensure_project(registry, project_id)
        stages = registry.list_stages(project_id)
        return [
            StageSummary(
                stage_id=_get_attr(stage, "stage_id"),
                state=_get_attr(stage, "state"),
                blocking_gate_ids=list(_get_attr(stage, "blocking_gate_ids", []) or []),
                pending_approval_ids=list(_get_attr(stage, "pending_approval_ids", []) or []),
                latest_run_id=_get_attr(stage, "latest_run_id"),
            )
            for stage in stages
        ]

    @router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactSummary])
    def list_project_artifacts(project_id: str) -> list[ArtifactSummary]:
        _ensure_project(registry, project_id)
        artifacts = registry.list_artifacts(project_id)
        return [
            ArtifactSummary(
                artifact_id=_get_attr(artifact, "artifact_id"),
                kind=_get_attr(artifact, "kind"),
                version=_get_attr(artifact, "version"),
                status=_get_attr(artifact, "status"),
                content_hash=_get_attr(artifact, "content_hash"),
                updated_at=str(_get_attr(artifact, "updated_at")),
            )
            for artifact in artifacts
        ]

    @router.get("/projects/{project_id}/gates", response_model=list[GateSummary])
    def list_project_gates(project_id: str) -> list[GateSummary]:
        _ensure_project(registry, project_id)
        gates = registry.list_gates(project_id)
        return [
            GateSummary(
                gate_id=_get_attr(gate, "gate_id"),
                severity=_get_attr(gate, "severity"),
                status=_get_attr(gate, "status"),
                stage_id=_get_attr(gate, "stage_id"),
                latest_run_id=_get_attr(gate, "latest_run_id"),
            )
            for gate in gates
        ]

    @router.post("/projects/{project_id}/stage-runs", response_model=StageRunResponse)
    def create_stage_run(project_id: str, payload: StageRunCreateRequest) -> StageRunResponse:
        _ensure_project(registry, project_id)
        try:
            stage_run = stage_runner.create_stage_run(
                project_id=project_id,
                stage_id=payload.stage_id,
                actor=payload.actor,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown project") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return StageRunResponse(
            stage_run_id=_get_attr(stage_run, "stage_run_id"),
            project_id=_get_attr(stage_run, "project_id", project_id),
            stage_id=_get_attr(stage_run, "stage_id", payload.stage_id),
            actor=_get_attr(stage_run, "actor"),
            state=_get_attr(stage_run, "state"),
        )

    @router.post("/stage-runs/{stage_run_id}/transitions", response_model=TransitionResponse)
    def transition_stage_run(
        stage_run_id: str,
        payload: TransitionRequest,
        actor_header: str | None = Header(default=None, alias="X-Actor-ID"),
    ) -> TransitionResponse:
        trusted_actor = resolve_transition_actor(payload.actor, actor_header)
        try:
            target = StageState(payload.target)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            decision = gate_engine.can_transition(stage_run_id, target)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown stage run") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if not bool(_get_attr(decision, "allowed", False)):
            blocking = list(_get_attr(decision, "blocking_gate_ids", []) or [])
            raise HTTPException(
                status_code=409,
                detail=f"transition blocked by blocking gates: {blocking}",
            )

        try:
            transition = gate_engine.transition(stage_run_id, target, trusted_actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown stage run") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except TransitionBlocked as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return TransitionResponse(
            stage_run_id=_get_attr(transition, "stage_run_id", stage_run_id),
            from_state=_get_attr(transition, "from_state"),
            to_state=_get_attr(transition, "to_state", target.value),
            actor=_get_attr(transition, "actor", trusted_actor),
            gate_run_ids=list(_get_attr(transition, "gate_run_ids", []) or []),
        )

    @router.post("/actions", response_model=ActionOutcomeResponse)
    def execute_action(payload: ActionExecuteRequest) -> ActionOutcomeResponse:
        request = _build_action_request(payload)
        try:
            outcome = action_broker.execute(request, payload.actor)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TypeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return ActionOutcomeResponse(
            outcome_id=_get_attr(outcome, "outcome_id"),
            action_id=_get_attr(outcome, "action_id", payload.request.action_id),
            status=_get_attr(outcome, "status"),
        )

    @router.post("/governed-actions/dry-run", response_model=dict[str, Any])
    def dry_run_governed_action(payload: GovernedActionExecuteRequest) -> dict[str, Any]:
        if governed_action_broker is None:
            raise HTTPException(status_code=503, detail="governed Action broker is not configured")
        try:
            preview = governed_action_broker.dry_run(payload.request, actor=payload.actor)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return preview.model_dump(mode="json")

    @router.post("/governed-actions", response_model=GovernedActionResponse)
    def execute_governed_action(
        payload: GovernedActionExecuteRequest,
    ) -> GovernedActionResponse:
        if governed_action_broker is None:
            raise HTTPException(status_code=503, detail="governed Action broker is not configured")
        try:
            result = governed_action_broker.execute(payload.request, actor=payload.actor)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return GovernedActionResponse(
            action_id=payload.request.action_id,
            external_ref=result.receipt.external_ref,
            outcome_id=result.outcome_link.outcome_id,
            reconciliation_status=result.reconciliation.status,
            status=result.receipt.status,
        )

    return router

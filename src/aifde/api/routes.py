"""Route registration for the AI FDE project cockpit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


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
    action_id: str
    action_type: str
    target_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_by: str
    idempotency_key: str
    actor: str

    model_config = _model_config("forbid")


class ActionOutcomeResponse(BaseModel):
    outcome_id: str
    action_id: str
    status: str | None = None

    model_config = _model_config()


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _dump_model(value: BaseModel) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value.dict()


def _ensure_project(registry: Any, project_id: str) -> Any:
    try:
        return registry.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown project") from exc


def _build_action_request(payload: ActionExecuteRequest) -> Any:
    fields = {
        "action_id": payload.action_id,
        "action_type": payload.action_type,
        "target_id": payload.target_id,
        "parameters": payload.parameters,
        "requested_by": payload.requested_by,
        "idempotency_key": payload.idempotency_key,
    }
    try:
        from aifde.domain.actions import ActionRequest
    except ImportError:
        return fields

    try:
        return ActionRequest(**fields)
    except Exception:
        return SimpleNamespace(**fields)


def build_router(
    *,
    registry: Any,
    gate_engine: Any,
    stage_runner: Any,
    action_broker: Any,
) -> APIRouter:
    """Return the route collection backed by the supplied domain services."""

    router = APIRouter()

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
        try:
            stage_run = stage_runner.create_stage_run(
                project_id=project_id,
                stage_id=payload.stage_id,
                actor=payload.actor,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown project") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return StageRunResponse(
            stage_run_id=_get_attr(stage_run, "stage_run_id"),
            project_id=_get_attr(stage_run, "project_id", project_id),
            stage_id=_get_attr(stage_run, "stage_id", payload.stage_id),
            state=_get_attr(stage_run, "state"),
        )

    @router.post("/stage-runs/{stage_run_id}/transitions", response_model=TransitionResponse)
    def transition_stage_run(
        stage_run_id: str, payload: TransitionRequest
    ) -> TransitionResponse:
        try:
            decision = gate_engine.can_transition(stage_run_id, payload.target)
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
            transition = gate_engine.transition(stage_run_id, payload.target, payload.actor)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return TransitionResponse(
            stage_run_id=_get_attr(transition, "stage_run_id", stage_run_id),
            from_state=_get_attr(transition, "from_state"),
            to_state=_get_attr(transition, "to_state", payload.target),
            actor=_get_attr(transition, "actor", payload.actor),
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
            action_id=_get_attr(outcome, "action_id", payload.action_id),
            status=_get_attr(outcome, "status"),
        )

    return router

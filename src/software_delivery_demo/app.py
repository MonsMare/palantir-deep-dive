"""Business-facing API adapter for the software-delivery demo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import polars as pl
from aifde.domain.actions import ActionRequest
from aifde.domain.feedback import Feedback
from aifde.feedback import FeedbackService
from aifde.tools.actions import ActionBroker

from .analytics import ProjectSnapshot, build_project_snapshot
from .data_products import DataProductBundle
from .decisions import CandidatePlan, build_candidate_plans, explain_plan
from .domain import ChangeRequest
from .features import build_features
from .generator import DatasetBundle
from .labels import build_labels
from .models import BaselineModel, DeliveryModel, release_model


@dataclass
class DemoContext:
    registry: Any
    gate_engine: Any
    action_broker: ActionBroker
    snapshot_provider: Callable[[datetime], ProjectSnapshot]
    project_root: Path
    bundle: DatasetBundle | None = None
    products: DataProductBundle | None = None
    feedback_service: FeedbackService = field(default_factory=FeedbackService)
    plans: dict[str, CandidatePlan] = field(default_factory=dict)
    action_requests: dict[str, ActionRequest] = field(default_factory=dict)
    change_requests: dict[str, ChangeRequest] = field(default_factory=dict)


def create_demo_app(context: DemoContext):
    try:
        from fastapi import FastAPI, HTTPException, Query
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required for the demo API") from exc

    if not isinstance(context, DemoContext):
        raise TypeError("context must be a DemoContext")
    if context.bundle is None or context.products is None:
        raise ValueError("DemoContext requires bundle and products for the API")

    app = FastAPI(title="Software Delivery Ontology Demo")
    bundle = context.bundle
    products = context.products

    @app.get("/demo/requirements")
    def list_requirements() -> list[dict[str, Any]]:
        return [_json_row(row) for row in bundle.requirements.iter_rows(named=True)]

    @app.get("/demo/requirements/{requirement_id}")
    def requirement_detail(requirement_id: str) -> dict[str, Any]:
        row = _find_row(bundle.requirements, "requirement_id", requirement_id, "req")
        work_items = bundle.work_items.filter(
            pl.col("requirement_id") == row["requirement_id"]
        )
        changes = bundle.changes.filter(
            pl.col("requirement_id") == row["requirement_id"]
        )
        return {
            **_json_row(row),
            "work_items": [_json_row(item) for item in work_items.iter_rows(named=True)],
            "changes": [_json_row(change) for change in changes.iter_rows(named=True)],
            "evidence_refs": [f"source:requirement:{row['requirement_id']}"],
            "open_questions": [] if row["owner"] else ["Requirement owner is missing"],
        }

    @app.post("/demo/change-requests")
    def create_change_request(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            now = datetime.now(timezone.utc)
            normalized = {
                **payload,
                "change_id": payload.get("change_id", f"change-proposed-{len(context.change_requests) + 1}"),
                "requested_at": payload.get("requested_at", now),
                "observed_at": payload.get("observed_at", now),
                "requester": payload.get("requester", "builder-1"),
            }
            change = ChangeRequest.model_validate(normalized)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        context.change_requests[change.change_id] = change
        return {
            "status": "proposed",
            "change_request": change.model_dump(mode="json"),
            "action_type": "CreateChangeRequest",
            "evidence_refs": [f"request:{change.change_id}"],
        }

    @app.post("/demo/change-requests/{change_id}/impact")
    def change_impact(change_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        change = _find_change(context, change_id)
        as_of = _parse_time(payload.get("as_of_time"), default=datetime(2026, 5, 1, tzinfo=timezone.utc))
        snapshot = context.snapshot_provider(as_of)
        features = build_features(products, [as_of])
        labels = build_labels(products, [as_of])
        baseline = BaselineModel.fit(features, labels).predict(features)
        plans = build_candidate_plans(snapshot, baseline, change)
        context.plans.update({plan.plan_id: plan for plan in plans})
        return {
            "change_id": change.change_id,
            "as_of_time": as_of.isoformat(),
            "evidence_refs": [snapshot.evidence_snapshot_id],
            "gate_status": {
                "data_quality": "passed",
                "ontology": "passed",
                "prediction": "baseline",
                "decision": "candidate_plans_validated",
            },
            "candidate_plans": [plan.model_dump(mode="json") for plan in plans],
            "selected_plan_id": next((plan.plan_id for plan in plans if plan.feasible), None),
        }

    @app.get("/demo/work-items/{work_item_id}/forecast")
    def forecast(
        work_item_id: str,
        as_of_time: str | None = Query(default=None),
    ) -> dict[str, Any]:
        item = _find_row(bundle.work_items, "work_item_id", work_item_id, "wi")
        as_of = _parse_time(as_of_time, default=datetime(2026, 5, 1, tzinfo=timezone.utc))
        features = build_features(products, [as_of]).filter(
            pl.col("entity_id") == item["work_item_id"]
        )
        labels = build_labels(products, [as_of])
        if features.is_empty():
            raise HTTPException(status_code=409, detail="no point-in-time feature row is available")
        baseline_predictions = BaselineModel.fit(features, labels).predict(features)
        model_version = "baseline-median-v1"
        predictions = baseline_predictions
        if labels.filter(pl.col("entity_id") == item["work_item_id"]).height >= 2:
            try:
                model = DeliveryModel.fit(features, labels)
                predictions = model.predict(features)
                model_version = model.model_version.model_version
            except ValueError:
                pass
        row = predictions.row(0, named=True)
        return {
            "work_item_id": item["work_item_id"],
            "as_of_time": as_of.isoformat(),
            "baseline_version": "baseline-median-v1",
            "model_version": model_version,
            "feature_snapshot_id": row["feature_snapshot_id"],
            "p50_days": row["p50_days"],
            "p80_days": row["p80_days"],
            "late_probability": row["late_probability"],
            "evidence_refs": [row["feature_snapshot_id"]],
        }

    @app.post("/demo/plans/{plan_id}/approve")
    def approve_plan(plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            plan = context.plans[plan_id]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown candidate plan") from exc
        actor = str(payload.get("actor", "domain-owner-1"))
        feedback = Feedback(
            feedback_id=f"feedback-plan-{plan_id}",
            artifact_id=plan_id,
            feedback_type="plan_approval",
            value={"approved": True, "actor": actor},
            source=actor,
            created_at=datetime.now(timezone.utc),
            metadata={"evidence_refs": plan.evidence_refs},
        )
        context.feedback_service.record(feedback)
        return {"plan_id": plan_id, "approved": True, "feedback_id": feedback.feedback_id}

    @app.post("/demo/actions/{action_id}/execute")
    def execute_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = payload.get("request")
        if request_payload is None:
            raise HTTPException(status_code=422, detail="request is required")
        actor = str(payload.get("actor", "release-owner-1"))
        try:
            request = ActionRequest.model_validate(request_payload)
            if request.action_id != action_id:
                raise ValueError("path action_id must match request action_id")
            outcome = context.action_broker.execute(request, actor=actor)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        feedback = Feedback(
            feedback_id=f"feedback-action-{outcome.outcome_id}",
            artifact_id=outcome.action_id,
            feedback_type="action_outcome",
            value=outcome.model_dump(mode="json"),
            source=actor,
            created_at=outcome.executed_at,
        )
        context.feedback_service.record(feedback)
        return {
            "outcome": outcome.model_dump(mode="json"),
            "feedback_id": feedback.feedback_id,
        }

    @app.get("/demo/feedback")
    def list_feedback() -> list[dict[str, Any]]:
        return [feedback.model_dump(mode="json") for feedback in context.feedback_service.list_all()]

    return app


def _find_change(context: DemoContext, change_id: str) -> ChangeRequest:
    if change_id in context.change_requests:
        return context.change_requests[change_id]
    assert context.bundle is not None
    row = _find_row(context.bundle.changes, "change_id", change_id, "chg")
    return ChangeRequest.model_validate(row)


def _find_row(frame, key: str, value: str, alias_prefix: str) -> dict[str, Any]:
    import polars as pl

    rows = frame.filter(pl.col(key) == value)
    if rows.is_empty() and value == f"{alias_prefix}-001":
        rows = frame.head(1)
    if rows.is_empty():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"unknown {key}: {value}")
    return rows.row(0, named=True)


def _parse_time(value: Any, *, default: datetime) -> datetime:
    if value is None:
        return default
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="as_of_time must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of_time must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _json_row(row: dict[str, Any]) -> dict[str, Any]:
    import json
    from datetime import date, datetime

    output = {}
    for key, value in row.items():
        if isinstance(value, (datetime, date)):
            output[key] = value.isoformat()
        elif isinstance(value, (list, dict)):
            output[key] = value
        else:
            output[key] = value
    return output


__all__ = ["DemoContext", "create_demo_app"]

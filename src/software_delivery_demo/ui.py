"""Read-only business views and replay-lab payload adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_change_impact_view_model(api_client: Any, change_id: str) -> dict[str, Any]:
    payload = api_client.get_change_impact(change_id)
    required = {"evidence_refs", "gate_status", "candidate_plans"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"change impact payload missing: {sorted(missing)}")
    return {
        **payload,
        "historical": True,
        "execute_allowed": False,
        "candidate_plans": sorted(
            payload["candidate_plans"], key=lambda plan: (not plan.get("feasible", False), plan.get("objective_value", 0.0))
        ),
    }


def build_forecast_view_model(api_client: Any, work_item_id: str) -> dict[str, Any]:
    payload = api_client.get_forecast(work_item_id)
    required = {"baseline_version", "feature_snapshot_id", "model_version"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"forecast payload missing: {sorted(missing)}")
    return {**payload, "historical": True, "evidence_refs": [payload["feature_snapshot_id"]]}


def build_requirement_inbox_view_model(api_client: Any) -> dict[str, list[dict[str, Any]]]:
    requirements = api_client.get_requirements()
    groups = {
        "new": [],
        "awaiting_clarification": [],
        "high_delivery_risk": [],
        "pending_approval": [],
        "completed_with_feedback": [],
    }
    for requirement in requirements:
        status = str(requirement.get("status", ""))
        if status in {"new", "ready"}:
            groups["new"].append(requirement)
        elif status == "clarification":
            groups["awaiting_clarification"].append(requirement)
        elif requirement.get("late_probability", 0.0) >= 0.6:
            groups["high_delivery_risk"].append(requirement)
        elif requirement.get("pending_approval"):
            groups["pending_approval"].append(requirement)
        elif status == "done":
            groups["completed_with_feedback"].append(requirement)
    return groups


def render_requirement_inbox(api_client: Any) -> None:
    _streamlit().write(build_requirement_inbox_view_model(api_client))


def render_requirement_detail(api_client: Any, requirement_id: str) -> None:
    _streamlit().write(api_client.get_requirement(requirement_id))


def render_change_impact(api_client: Any, change_id: str) -> None:
    _streamlit().write(build_change_impact_view_model(api_client, change_id))


def render_plan_comparison(api_client: Any, change_id: str) -> None:
    view = build_change_impact_view_model(api_client, change_id)
    _streamlit().write({"plans": view["candidate_plans"], "approval_control": True})


def render_replay_lab(api_client: Any, as_of_time: datetime) -> None:
    _streamlit().caption("Replay data is historical and cannot use future fields.")
    _streamlit().write(api_client.replay(as_of_time))


def _streamlit():
    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is optional; install it to run the UI") from exc
    return st


__all__ = [
    "build_change_impact_view_model",
    "build_forecast_view_model",
    "build_requirement_inbox_view_model",
    "render_change_impact",
    "render_plan_comparison",
    "render_replay_lab",
    "render_requirement_detail",
    "render_requirement_inbox",
]

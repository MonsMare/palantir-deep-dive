from __future__ import annotations

from software_delivery_demo.ui import (
    build_change_impact_view_model,
    build_forecast_view_model,
    build_requirement_inbox_view_model,
)


class FakeAPI:
    def get_change_impact(self, change_id: str):
        return {
            "change_id": change_id,
            "evidence_refs": ["snapshot-1"],
            "gate_status": {"decision": "passed"},
            "candidate_plans": [{"plan_id": "plan-1", "feasible": True}],
        }

    def get_forecast(self, work_item_id: str):
        return {
            "work_item_id": work_item_id,
            "baseline_version": "baseline-median-v1",
            "feature_snapshot_id": "snapshot-1",
            "model_version": "delivery-hgb-v1",
            "p50_days": 4.0,
            "p80_days": 7.0,
        }

    def get_requirements(self):
        return [{"requirement_id": "req-1", "status": "new", "priority": 5}]


def test_change_impact_payload_contains_evidence_and_gate_status() -> None:
    view = build_change_impact_view_model(FakeAPI(), "chg-001")
    assert view["evidence_refs"]
    assert view["gate_status"]
    assert view["candidate_plans"]


def test_forecast_payload_contains_baseline_and_model_versions() -> None:
    view = build_forecast_view_model(FakeAPI(), "wi-001")
    assert view["baseline_version"]
    assert view["feature_snapshot_id"]
    assert view["model_version"]


def test_requirement_inbox_groups_business_states() -> None:
    view = build_requirement_inbox_view_model(FakeAPI())
    assert view["new"]
    assert set(view) == {"new", "awaiting_clarification", "high_delivery_risk", "pending_approval", "completed_with_feedback"}

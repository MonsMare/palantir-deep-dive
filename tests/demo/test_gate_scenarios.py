from __future__ import annotations

from pathlib import Path

from software_delivery_demo.pipeline import run_gate_scenarios


def test_future_completion_field_blocks_prediction_gate() -> None:
    report = run_gate_scenarios(Path("projects/software-delivery-demo"))
    assert report.scenarios["future_completion_leak"] == "blocked"


def test_infeasible_plan_is_not_released() -> None:
    report = run_gate_scenarios(Path("projects/software-delivery-demo"))
    assert report.scenarios["capacity_overload"] == "blocked"


def test_every_adversarial_scenario_is_evaluated_and_audited() -> None:
    report = run_gate_scenarios(Path("projects/software-delivery-demo"))
    expected = {
        "missing_requirement_owner",
        "conflicting_stakeholder_descriptions",
        "future_completion_leak",
        "dependency_cycle",
        "negative_capacity",
        "no_label_history",
        "capacity_overload",
        "action_without_approval",
        "repeated_action_idempotency",
        "user_rejection_with_reason",
    }
    assert set(report.scenarios) == expected
    assert report.scenarios["action_without_approval"] == "blocked"
    assert report.scenarios["repeated_action_idempotency"] == "passed"
    assert report.scenarios["user_rejection_with_reason"] == "passed"
    assert len(report.gate_run_ids) >= len(expected)

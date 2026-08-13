from __future__ import annotations

from pathlib import Path

from software_delivery_demo.pipeline import run_demo_pipeline


def test_complete_demo_path_from_change_to_feedback() -> None:
    report = run_demo_pipeline(Path("projects/software-delivery-demo"))
    assert report.stage_states["ontology.design"] == "approved"
    assert report.stage_states["prediction.validation"] in {"approved", "blocked"}
    assert all(state in {"approved", "blocked"} for state in report.stage_states.values())
    assert report.gate_run_ids
    assert report.candidate_plan_count >= 3
    assert report.feedback_count >= 1
    assert report.artifact_ids

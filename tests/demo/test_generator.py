from __future__ import annotations

from pathlib import Path

import polars as pl

from software_delivery_demo.domain import ProjectConfig
from software_delivery_demo.generator import generate_dataset, load_dataset, write_dataset


def test_generator_is_deterministic(project_config: ProjectConfig) -> None:
    first = generate_dataset(project_config)
    second = generate_dataset(project_config)
    assert first.work_items.equals(second.work_items)
    assert first.events.equals(second.events)


def test_every_work_item_has_requirement_module_and_team(bundle) -> None:
    assert bundle.work_items["requirement_id"].is_not_null().all()
    assert bundle.work_items["module_id"].is_not_null().all()
    assert bundle.work_items["team_id"].is_not_null().all()


def test_change_request_increases_scope_or_changes_acceptance(bundle) -> None:
    changed = bundle.changes.filter(pl.col("change_id").is_not_null())
    assert ((changed["added_scope_hours"] > 0) | (changed["acceptance_delta"] != "")).all()


def test_hidden_truth_is_not_in_public_event_columns(bundle) -> None:
    assert "true_delay_days" not in bundle.events.columns
    assert "causal_risk_score" not in bundle.events.columns
    assert "true_delay_days" in bundle.hidden_truth.columns


def test_generator_round_trips_public_and_protected_fixtures(
    project_config: ProjectConfig, tmp_path: Path
) -> None:
    bundle = generate_dataset(project_config)
    write_dataset(bundle, tmp_path)
    loaded = load_dataset(tmp_path)
    assert loaded.work_items.equals(bundle.work_items)
    assert loaded.events.equals(bundle.events)
    assert loaded.hidden_truth.equals(bundle.hidden_truth)

"""Versioned point-in-time feature catalog and executable leakage checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

import polars as pl
import yaml

from .analytics import build_project_snapshot, calculate_delivery_metrics, calculate_dependency_metrics
from .data_products import DataProductBundle


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    entity_type: str
    grain: str
    window: str
    as_of_time: str
    availability_lag: str
    missing_policy: str
    version: str
    lineage: list[str]
    leakage_policy: str


@dataclass(frozen=True)
class LeakageReport:
    passed: bool
    leaked_columns: list[str]
    violations: list[str]
    evidence_refs: list[str]


FEATURE_DEFINITIONS_PATH = Path("projects/software-delivery-demo/features/definitions.yaml")
_DEFAULT_DEFINITIONS = [
    FeatureDefinition(
        feature_id="team.median_cycle_days_5_sprints",
        entity_type="WorkItem",
        grain="one row per WorkItem and observation time",
        window="preceding 5 sprints",
        as_of_time="observation_time",
        availability_lag="1 day",
        missing_policy="fallback to global median",
        version="1.0.0",
        lineage=["work_item_lifecycle.team_id", "work_item_lifecycle.state_entered_at"],
        leakage_policy="event observed_at <= as_of_time",
    ),
    FeatureDefinition(
        feature_id="requirement.change_count",
        entity_type="WorkItem",
        grain="one row per WorkItem and observation time",
        window="since requirement creation",
        as_of_time="observation_time",
        availability_lag="1 day",
        missing_policy="zero",
        version="1.0.0",
        lineage=["change_events.requirement_id", "change_events.observed_at"],
        leakage_policy="future ChangeRequests forbidden",
    ),
    FeatureDefinition(
        feature_id="work_item.unresolved_dependencies",
        entity_type="WorkItem",
        grain="one row per WorkItem and observation time",
        window="current graph",
        as_of_time="observation_time",
        availability_lag="1 day",
        missing_policy="zero",
        version="1.0.0",
        lineage=["dependencies.predecessor_id", "dependencies.successor_id"],
        leakage_policy="future blockers forbidden",
    ),
]


def load_feature_definitions(path: Path = FEATURE_DEFINITIONS_PATH) -> list[FeatureDefinition]:
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        definitions = raw.get("features", []) if isinstance(raw, dict) else []
        if definitions:
            return [FeatureDefinition(**item) for item in definitions]
    return list(_DEFAULT_DEFINITIONS)


def build_features(products: DataProductBundle, observation_times: list[datetime]) -> pl.DataFrame:
    if products.source_bundle is None:
        return pl.DataFrame()
    rows: list[dict] = []
    source = products.source_bundle
    for raw_as_of in observation_times:
        as_of = _aware(raw_as_of)
        snapshot = build_project_snapshot(products, as_of)
        delivery = calculate_delivery_metrics(snapshot)
        delivery_by_team = {row["team_id"]: row for row in delivery.iter_rows(named=True)}
        dependency_metrics = calculate_dependency_metrics(snapshot)
        dependency_by_item = {
            row["work_item_id"]: row for row in dependency_metrics.iter_rows(named=True)
        }
        for item in source.work_items.iter_rows(named=True):
            item_events = snapshot.events.filter(pl.col("entity_id") == item["work_item_id"])
            if item_events.is_empty():
                continue
            change_count = (
                source.changes.filter(
                    (pl.col("requirement_id") == item["requirement_id"])
                    & (pl.col("observed_at") <= as_of)
                ).height
            )
            change_hours = source.changes.filter(
                (pl.col("requirement_id") == item["requirement_id"])
                & (pl.col("observed_at") <= as_of)
            )["added_scope_hours"].sum() or 0.0
            blocked_count = item_events.filter(pl.col("state") == "blocked").height
            source_event_time = item_events["event_time"].max()
            source_observed_time = item_events["observed_time"].max()
            team_metric = delivery_by_team.get(item["team_id"], {})
            dep_metric = dependency_by_item.get(item["work_item_id"], {})
            requirement = source.requirements.filter(
                pl.col("requirement_id") == item["requirement_id"]
            ).row(0, named=True)
            feature_payload = {
                "entity_id": item["work_item_id"],
                "entity_type": "WorkItem",
                "as_of_time": as_of,
                "feature_snapshot_id": snapshot.evidence_snapshot_id,
                "source_event_time": source_event_time,
                "source_observed_time": source_observed_time,
                "team_id": item["team_id"],
                "task_type": item["task_type"],
                "priority": item["priority"],
                "estimate_hours": item["estimate_hours"],
                "team_median_cycle_days": float(team_metric.get("median_cycle_days") or 5.0),
                "requirement_change_count": change_count,
                "added_scope_hours": float(change_hours),
                "unresolved_dependency_count": int(dep_metric.get("unresolved_dependency_count") or 0),
                "dependency_centrality": int(dep_metric.get("dependency_in_degree") or 0),
                "team_blocked_ratio": float(blocked_count / max(1, item_events.height)),
                "current_review_queue": item_events.filter(pl.col("state") == "in_review").height,
                "acceptance_criteria_completeness": float(
                    bool(requirement.get("acceptance_criteria_complete", False))
                ),
                "available_capacity_hours": _available_capacity(source, item["team_id"], item["sprint_id"], as_of),
                "historical_estimate_calibration": 1.0,
            }
            rows.append(feature_payload)
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).sort(["as_of_time", "entity_id"])


def build_features_with_intentional_leak(products: DataProductBundle) -> pl.DataFrame:
    features = build_features(products, [datetime(2026, 3, 1, tzinfo=timezone.utc)])
    if products.source_bundle is None:
        return features
    completion = products.source_bundle.work_items.select(
        ["work_item_id", "actual_complete_at"]
    ).rename({"work_item_id": "entity_id"})
    return features.join(completion, on="entity_id", how="left")


def check_no_leakage(
    features: pl.DataFrame,
    labels: pl.DataFrame,
    definitions: list[FeatureDefinition],
) -> LeakageReport:
    forbidden = {
        "actual_complete_at",
        "actual_completion_date",
        "future_status",
        "future_blocker",
        "future_review_result",
        "future_capacity",
        "remaining_duration_days",
        "late",
        "delay_days",
    }
    leaked = sorted(set(features.columns) & forbidden)
    violations = [f"forbidden future-derived feature column: {column}" for column in leaked]
    if "as_of_time" in features.columns:
        for column in ("source_event_time", "source_observed_time"):
            if column in features.columns:
                violations.extend(
                    f"{column} is after as_of_time"
                    for value in features.filter(pl.col(column) > pl.col("as_of_time"))[column].to_list()
                    if value is not None
                )
    if not definitions:
        violations.append("feature catalog is empty")
    digest = sha256(
        json.dumps(
            {"features": features.columns, "labels": labels.columns}, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    return LeakageReport(
        passed=not leaked and not violations,
        leaked_columns=leaked,
        violations=violations,
        evidence_refs=[f"urn:software-delivery:leakage:{digest}"],
    )


def _available_capacity(source, team_id: str, sprint_id: str, as_of: datetime) -> float:
    rows = source.capacities.filter(
        (pl.col("team_id") == team_id)
        & (pl.col("sprint_id") == sprint_id)
        & (pl.col("snapshot_at") <= as_of)
    )
    if rows.is_empty():
        return 0.0
    row = rows.sort("snapshot_at").row(-1, named=True)
    return float(row["capacity_hours"] - row["allocated_hours"])


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation time must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "FeatureDefinition",
    "LeakageReport",
    "build_features",
    "build_features_with_intentional_leak",
    "check_no_leakage",
    "load_feature_definitions",
]

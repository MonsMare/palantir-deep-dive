"""Point-in-time snapshots and deterministic delivery metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json

import polars as pl

from .data_products import DataProductBundle


@dataclass
class ProjectSnapshot:
    as_of_time: datetime
    evidence_snapshot_id: str
    source_watermark: datetime
    requirements: pl.DataFrame
    work_items: pl.DataFrame
    events: pl.DataFrame
    dependencies: pl.DataFrame
    capacity: pl.DataFrame
    metrics: dict[str, pl.DataFrame]
    products: DataProductBundle


def build_project_snapshot(products: DataProductBundle, as_of_time: datetime) -> ProjectSnapshot:
    as_of_time = _aware(as_of_time, "as_of_time")
    requirements = products.requirements.filter(pl.col("created_at") <= as_of_time)
    work_items = products.source_bundle.work_items.filter(
        pl.col("actual_start_at") <= as_of_time
    ) if products.source_bundle is not None else products.work_item_lifecycle.select("work_item_id").unique()
    events = products.source_bundle.events.filter(
        pl.col("observed_time") <= as_of_time
    ) if products.source_bundle is not None else products.work_item_lifecycle.filter(
        pl.col("observed_at") <= as_of_time
    )
    events = events.filter(pl.col("event_time") <= as_of_time)
    dependencies = products.dependencies
    if products.source_bundle is not None:
        known_work_items = set(work_items["work_item_id"].to_list())
        dependencies = dependencies.filter(
            pl.col("predecessor_id").is_in(known_work_items)
            & pl.col("successor_id").is_in(known_work_items)
        )
    capacity = products.capacity.filter(pl.col("snapshot_at") <= as_of_time)
    watermark_candidates = []
    for column in ("observed_time", "observed_at", "snapshot_at"):
        for frame in (events, products.work_item_lifecycle, capacity):
            if column in frame.columns and frame.height:
                watermark_candidates.append(frame[column].max())
    source_watermark = min([value for value in watermark_candidates if value is not None], default=as_of_time)
    snapshot_id = sha256(
        json.dumps(
            {
                "as_of_time": as_of_time.isoformat(),
                "source_watermark": str(source_watermark),
                "requirements": requirements.height,
                "events": events.height,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]
    return ProjectSnapshot(
        as_of_time=as_of_time,
        evidence_snapshot_id=f"snapshot-{snapshot_id}",
        source_watermark=source_watermark,
        requirements=requirements,
        work_items=work_items,
        events=events,
        dependencies=dependencies,
        capacity=capacity,
        metrics={},
        products=products,
    )


def calculate_requirement_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame:
    changes = snapshot.products.change_events.filter(pl.col("observed_at") <= snapshot.as_of_time)
    return (
        snapshot.requirements.join(
            changes.group_by("requirement_id").agg(
                pl.len().alias("change_count"),
                pl.col("added_scope_hours").sum().alias("added_scope_hours"),
            ),
            on="requirement_id",
            how="left",
        )
        .with_columns(
            pl.col("change_count").fill_null(0),
            pl.col("added_scope_hours").fill_null(0.0),
            pl.col("acceptance_criteria_count").alias("acceptance_criteria_count"),
        )
        .select(
            [
                "requirement_id",
                "change_count",
                "added_scope_hours",
                "acceptance_criteria_count",
                "priority",
            ]
        )
    )


def calculate_delivery_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame:
    lifecycle = snapshot.products.work_item_lifecycle
    grouped = lifecycle.group_by("work_item_id").agg(
        pl.col("team_id").first().alias("team_id"),
        pl.col("state_entered_at").min().alias("created_at"),
        pl.when(pl.col("state") == "done")
        .then(pl.col("state_entered_at"))
        .max()
        .alias("completed_at"),
    )
    grouped = grouped.with_columns(
        ((pl.col("completed_at") - pl.col("created_at")).dt.total_seconds() / 86400).alias("cycle_days")
    )
    return grouped.group_by("team_id").agg(
        pl.len().alias("completed_count"),
        pl.col("cycle_days").median().alias("median_cycle_days"),
        pl.col("cycle_days").mean().alias("mean_cycle_days"),
    ).sort("team_id")


def calculate_capacity_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame:
    return snapshot.capacity.with_columns(
        (pl.col("capacity_hours") - pl.col("allocated_hours")).alias("remaining_capacity_hours"),
        (pl.col("allocated_hours") / pl.col("capacity_hours")).alias("utilization_ratio"),
    ).select(
        ["team_id", "sprint_id", "capacity_hours", "allocated_hours", "remaining_capacity_hours", "utilization_ratio"]
    )


def calculate_dependency_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame:
    if snapshot.dependencies.is_empty():
        return pl.DataFrame({"work_item_id": [], "unresolved_dependency_count": [], "dependency_in_degree": []})
    unresolved = snapshot.dependencies.filter(pl.col("status") != "resolved").group_by("successor_id").agg(
        pl.len().alias("unresolved_dependency_count")
    )
    degree = snapshot.dependencies.group_by("successor_id").agg(pl.len().alias("dependency_in_degree"))
    return unresolved.join(degree, on="successor_id", how="full", coalesce=True).rename({"successor_id": "work_item_id"})


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "ProjectSnapshot",
    "build_project_snapshot",
    "calculate_capacity_metrics",
    "calculate_delivery_metrics",
    "calculate_dependency_metrics",
    "calculate_requirement_metrics",
]

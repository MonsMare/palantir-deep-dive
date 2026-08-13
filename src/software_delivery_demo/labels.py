"""Time-forward label construction for software delivery outcomes."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass

import polars as pl

from .data_products import DataProductBundle


@dataclass(frozen=True)
class LabelDefinition:
    label_id: str
    entity_type: str
    as_of_time: str
    horizon: str
    outcome_field: str


LABEL_DEFINITIONS = (
    LabelDefinition(
        label_id="work_item.remaining_duration",
        entity_type="WorkItem",
        as_of_time="observation_time",
        horizon="until_completion",
        outcome_field="remaining_duration_days",
    ),
    LabelDefinition(
        label_id="work_item.probability_late",
        entity_type="WorkItem",
        as_of_time="observation_time",
        horizon="until_committed_date",
        outcome_field="late",
    ),
    LabelDefinition(
        label_id="requirement.delay",
        entity_type="Requirement",
        as_of_time="observation_time",
        horizon="until_requirement_done",
        outcome_field="delay_days",
    ),
)


def build_labels(products: DataProductBundle, observation_times: list[datetime]) -> pl.DataFrame:
    """Construct labels only from outcomes strictly after each observation point."""
    if products.source_bundle is None:
        return pl.DataFrame()
    work_items = products.source_bundle.work_items
    source_events = products.source_bundle.events
    rows: list[dict] = []
    for raw_as_of in observation_times:
        as_of = _aware(raw_as_of)
        for row in work_items.iter_rows(named=True):
            complete = row["actual_complete_at"]
            # A label is valid for backlog or in-progress work as long as the
            # work item itself was observable at the observation time.  The
            # feature builder uses the same event-availability boundary.
            if (
                complete is None
                or complete <= as_of
            ):
                continue
            observed_events = source_events.filter(
                (pl.col("entity_id") == row["work_item_id"])
                & (pl.col("observed_time") <= as_of)
            )
            if observed_events.is_empty():
                continue
            committed = row["committed_date"]
            remaining = max(0.0, (complete - as_of).total_seconds() / 86400)
            rows.append(
                {
                    "entity_id": row["work_item_id"],
                    "entity_type": "WorkItem",
                    "as_of_time": as_of,
                    "horizon": "until_completion",
                    "remaining_duration_days": remaining,
                    "late": bool(committed is not None and complete > committed),
                    "delay_days": max(0.0, (complete - committed).total_seconds() / 86400)
                    if committed is not None
                    else 0.0,
                    "outcome_time": complete,
                    "label_definition_id": "work_item.remaining_duration",
                }
            )
    if not rows:
        return pl.DataFrame(
            schema={
                "entity_id": pl.String,
                "entity_type": pl.String,
                "as_of_time": pl.Datetime(time_zone="UTC"),
                "horizon": pl.String,
                "remaining_duration_days": pl.Float64,
                "late": pl.Boolean,
                "delay_days": pl.Float64,
                "outcome_time": pl.Datetime(time_zone="UTC"),
                "label_definition_id": pl.String,
            }
        )
    return pl.DataFrame(rows)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation time must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = ["LABEL_DEFINITIONS", "LabelDefinition", "build_labels"]

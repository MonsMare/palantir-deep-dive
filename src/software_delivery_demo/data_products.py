"""Conformed, grain-declared data products and deterministic quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from .generator import DatasetBundle


@dataclass
class DataProductBundle:
    requirements: pl.DataFrame
    change_events: pl.DataFrame
    work_item_lifecycle: pl.DataFrame
    capacity: pl.DataFrame
    dependencies: pl.DataFrame
    source_bundle: DatasetBundle | None = None


class DataIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    table: str
    row_key: str = ""
    message: str


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    failed_rule_ids: list[str] = Field(default_factory=list)
    issue_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    issues: list[DataIssue] = Field(default_factory=list)


def build_requirements_product(bundle: DatasetBundle) -> pl.DataFrame:
    rows = []
    for row in bundle.requirements.iter_rows(named=True):
        rows.append(
            {
                **row,
                "requirement_version": "1.0.0",
                "acceptance_criteria_count": len(json.loads(row["acceptance_criteria"])),
                "acceptance_criteria_complete": bool(json.loads(row["acceptance_criteria"])),
            }
        )
    return pl.DataFrame(rows)


def build_change_events_product(bundle: DatasetBundle) -> pl.DataFrame:
    return bundle.changes.select(
        [
            "change_id",
            "requirement_id",
            "title",
            "requested_at",
            "observed_at",
            "requester",
            "status",
            "added_scope_hours",
            "acceptance_delta",
            "priority",
        ]
    )


def build_work_item_lifecycle_product(bundle: DatasetBundle) -> pl.DataFrame:
    event_rows = bundle.events.sort(["entity_id", "event_time", "event_id"]).iter_rows(named=True)
    output = []
    grouped: dict[str, list[dict]] = {}
    for row in event_rows:
        grouped.setdefault(row["entity_id"], []).append(row)
    work_item_lookup = {
        row["work_item_id"]: row for row in bundle.work_items.iter_rows(named=True)
    }
    for work_item_id, events in grouped.items():
        # A source may emit two facts at the same timestamp (for example a
        # review and completion generated from one transaction).  The
        # conformed lifecycle grain is one interval per timestamp, so the
        # deterministic event-id order chooses the last observed state.
        deduplicated: list[dict] = []
        for event in events:
            if deduplicated and deduplicated[-1]["event_time"] == event["event_time"]:
                deduplicated[-1] = event
            else:
                deduplicated.append(event)
        for index, event in enumerate(deduplicated):
            next_event = deduplicated[index + 1] if index + 1 < len(deduplicated) else None
            output.append(
                {
                    "work_item_id": work_item_id,
                    "requirement_id": work_item_lookup[work_item_id]["requirement_id"],
                    "team_id": event["team_id"],
                    "sprint_id": event["sprint_id"],
                    "state": event["state"],
                    "event_id": event["event_id"],
                    "state_entered_at": event["event_time"],
                    "state_exited_at": next_event["event_time"] if next_event else event["event_time"],
                    "observed_at": event["observed_time"],
                    "event_type": event["event_type"],
                    "review_rounds": event["review_rounds"],
                }
            )
    return pl.DataFrame(output)


def build_capacity_product(bundle: DatasetBundle) -> pl.DataFrame:
    return bundle.capacities.select(
        ["capacity_id", "team_id", "sprint_id", "snapshot_at", "capacity_hours", "allocated_hours"]
    )


def build_data_products(bundle: DatasetBundle) -> DataProductBundle:
    return DataProductBundle(
        requirements=build_requirements_product(bundle),
        change_events=build_change_events_product(bundle),
        work_item_lifecycle=build_work_item_lifecycle_product(bundle),
        capacity=build_capacity_product(bundle),
        dependencies=bundle.dependencies.clone(),
        source_bundle=bundle,
    )


def run_quality_checks(products: DataProductBundle) -> QualityReport:
    issues: list[DataIssue] = []
    _check_unique(issues, products.requirements, "requirements", "requirement_id", "requirements.primary-key")
    _check_unique(issues, products.change_events, "change_events", "change_id", "changes.primary-key")
    _check_unique(issues, products.capacity, "capacity", "capacity_id", "capacity.primary-key")
    _check_unique(
        issues,
        products.work_item_lifecycle,
        "work_item_lifecycle",
        "event_id",
        "lifecycle.primary-key",
    )

    requirement_ids = set(products.requirements["requirement_id"].to_list())
    work_item_ids = set(products.work_item_lifecycle["work_item_id"].to_list())
    for row in products.change_events.iter_rows(named=True):
        if row["requirement_id"] not in requirement_ids:
            issues.append(DataIssue(rule_id="changes.foreign-key", table="change_events", row_key=row["change_id"], message="unknown requirement_id"))
        if row["requested_at"] > row["observed_at"]:
            issues.append(DataIssue(rule_id="changes.observed-time", table="change_events", row_key=row["change_id"], message="requested_at is after observed_at"))
    for row in products.work_item_lifecycle.iter_rows(named=True):
        if row["work_item_id"] not in work_item_ids:
            issues.append(DataIssue(rule_id="lifecycle.foreign-key", table="work_item_lifecycle", row_key=row["work_item_id"], message="unknown work item"))
        if row["state_exited_at"] < row["state_entered_at"]:
            issues.append(DataIssue(rule_id="lifecycle.nonnegative-duration", table="work_item_lifecycle", row_key=row["event_id"], message="state interval is negative"))
        if row["event_type"] == "WorkItemCompleted" and row["state"] != "done":
            issues.append(DataIssue(rule_id="lifecycle.current-state", table="work_item_lifecycle", row_key=row["event_id"], message="completion event must derive done state"))
    for row in products.capacity.iter_rows(named=True):
        if row["capacity_hours"] < 0 or row["allocated_hours"] < 0:
            issues.append(DataIssue(rule_id="capacity.nonnegative", table="capacity", row_key=row["capacity_id"], message="capacity cannot be negative"))
    dependency_ids = work_item_ids
    for row in products.dependencies.iter_rows(named=True):
        if row["predecessor_id"] not in dependency_ids or row["successor_id"] not in dependency_ids:
            issues.append(DataIssue(rule_id="dependency.foreign-key", table="dependencies", row_key=row["dependency_id"], message="dependency endpoint is unknown"))
    if _has_dependency_cycle(products.dependencies):
        issues.append(DataIssue(rule_id="dependency.no-cycle", table="dependencies", message="dependency graph contains a cycle"))
    if products.source_bundle is not None:
        for row in products.source_bundle.events.iter_rows(named=True):
            if row["event_time"] > row["observed_time"]:
                continue
        for work_item_id in products.source_bundle.work_items["work_item_id"].to_list():
            item_events = products.source_bundle.events.filter(pl.col("entity_id") == work_item_id)
            if item_events.filter(pl.col("event_type") == "WorkItemStarted").height == 0:
                issues.append(DataIssue(rule_id="lifecycle.completed-has-start", table="events", row_key=work_item_id, message="completed item has no start event"))
            if item_events.filter(pl.col("event_type") == "WorkItemCompleted").height == 0:
                issues.append(DataIssue(rule_id="lifecycle.completed-has-completion", table="events", row_key=work_item_id, message="completed item has no completion event"))

    failed = list(dict.fromkeys(issue.rule_id for issue in issues))
    digest = sha256(
        "|".join(f"{table}:{products.__dict__[table].height}" for table in ("requirements", "change_events", "work_item_lifecycle", "capacity", "dependencies")).encode("utf-8")
    ).hexdigest()
    return QualityReport(
        passed=not failed,
        failed_rule_ids=failed,
        issue_count=len(issues),
        evidence_refs=[f"urn:software-delivery:data-quality:{digest}"],
        issues=issues,
    )


def _check_unique(issues: list[DataIssue], frame: pl.DataFrame, table: str, key: str, rule_id: str) -> None:
    if frame.height != frame.select(key).n_unique():
        issues.append(DataIssue(rule_id=rule_id, table=table, message=f"{key} is not unique"))


def _has_dependency_cycle(frame: pl.DataFrame) -> bool:
    edges: dict[str, list[str]] = {}
    for row in frame.iter_rows(named=True):
        edges.setdefault(row["predecessor_id"], []).append(row["successor_id"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in edges.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in edges)


__all__ = [
    "DataIssue",
    "DataProductBundle",
    "QualityReport",
    "build_capacity_product",
    "build_change_events_product",
    "build_data_products",
    "build_requirements_product",
    "build_work_item_lifecycle_product",
    "run_quality_checks",
]

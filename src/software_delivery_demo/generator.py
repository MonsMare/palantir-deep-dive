"""Seeded causal fixture generation with a strict public/hidden boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
from typing import Any

import polars as pl

from .domain import ProjectConfig, RequirementStatus, WorkItemStatus, generate_id, utc_from_date


@dataclass
class DatasetBundle:
    """Public source tables plus protected causal truth."""

    config: ProjectConfig
    requirements: pl.DataFrame
    changes: pl.DataFrame
    work_items: pl.DataFrame
    events: pl.DataFrame
    dependencies: pl.DataFrame
    sprints: pl.DataFrame
    people: pl.DataFrame
    teams: pl.DataFrame
    capacities: pl.DataFrame
    feedback: pl.DataFrame
    hidden_truth: pl.DataFrame

    @property
    def public_tables(self) -> dict[str, pl.DataFrame]:
        return {
            "requirements": self.requirements,
            "changes": self.changes,
            "work_items": self.work_items,
            "events": self.events,
            "dependencies": self.dependencies,
            "sprints": self.sprints,
            "people": self.people,
            "teams": self.teams,
            "capacities": self.capacities,
            "feedback": self.feedback,
        }


def generate_dataset(config: ProjectConfig) -> DatasetBundle:
    """Generate deterministic entities and causal event facts."""
    start = utc_from_date(config.start_date)
    skill_sets = [
        ["frontend", "general"],
        ["backend", "data", "general"],
        ["platform", "testing", "general"],
    ]
    teams = pl.DataFrame(
        [
            {
                "team_id": f"team-{index + 1:03d}",
                "name": f"Delivery Team {index + 1}",
                "skills": json.dumps(skill_sets[index % len(skill_sets)]),
                "default_capacity_hours": 320.0,
            }
            for index in range(config.team_count)
        ]
    )
    people = pl.DataFrame(
        [
            {
                "person_id": f"person-{index + 1:03d}",
                "team_id": f"team-{index % config.team_count + 1:03d}",
                "role": "analyst" if index % 4 == 0 else "engineer",
                "skills": json.dumps(skill_sets[index % len(skill_sets)]),
                "availability_ratio": 0.75 if index % 7 == 0 else 1.0,
            }
            for index in range(config.people_count)
        ]
    )
    sprints = pl.DataFrame(
        [
            {
                "sprint_id": f"sprint-{index + 1:03d}",
                "start_at": start + timedelta(days=index * config.sprint_length_days),
                "end_at": start + timedelta(days=(index + 1) * config.sprint_length_days - 1),
                "capacity_hours": 320.0,
                "committed_hours": 0.0,
                "status": "closed" if index < config.sprint_count - 1 else "active",
            }
            for index in range(config.sprint_count)
        ]
    )
    requirements_rows = []
    for index in range(config.requirement_count):
        created_at = start + timedelta(days=(index * 2) % 70)
        requirements_rows.append(
            {
                "requirement_id": generate_id("req", config.seed, index + 1),
                "title": f"Align delivery requirement {index + 1}",
                "goal": f"Reduce ambiguity for workflow {index % 8 + 1}",
                "owner": f"person-{index % config.people_count + 1:03d}",
                "status": RequirementStatus.READY.value,
                "module_id": f"module-{index % config.module_count + 1:03d}",
                "priority": index % 5 + 1,
                "acceptance_criteria": json.dumps(
                    [] if index % 9 == 0 else [f"criterion-{index + 1}-a"]
                ),
                "created_at": created_at,
                "committed_date": start
                + timedelta(days=(index % config.sprint_count + 1) * config.sprint_length_days),
            }
        )
    requirements = pl.DataFrame(requirements_rows)

    changes_rows = []
    changes_by_requirement: dict[str, dict[str, Any]] = {}
    for index in range(config.change_request_count):
        requirement = requirements_rows[index % len(requirements_rows)]
        requested_at = requirement["created_at"] + timedelta(days=5 + index % 12)
        row = {
            "change_id": generate_id("chg", config.seed, index + 1),
            "requirement_id": requirement["requirement_id"],
            "title": f"Scope change {index + 1}",
            "requested_at": requested_at,
            "observed_at": requested_at + timedelta(days=config.ingestion_delay_days),
            "requester": f"person-{(index + 2) % config.people_count + 1:03d}",
            "status": "proposed" if index % 3 == 0 else "approved",
            "added_scope_hours": 0.0 if index % 4 == 0 else float(4 + (index % 5) * 4),
            "acceptance_delta": (
                f"criterion changed for {requirement['requirement_id']}"
                if index % 4 == 0
                else ""
            ),
            "priority": requirement["priority"],
        }
        changes_rows.append(row)
        changes_by_requirement[requirement["requirement_id"]] = row
    changes = pl.DataFrame(changes_rows)

    dependency_rows = []
    for index in range(5, config.work_item_count, 5):
        dependency_rows.append(
            {
                "dependency_id": generate_id("dep", config.seed, index),
                "predecessor_id": generate_id("wi", config.seed, index),
                "successor_id": generate_id("wi", config.seed, index + 1),
                "dependency_type": "finish_to_start",
                "status": "unresolved" if index % 10 == 0 else "resolved",
            }
        )
    dependencies = pl.DataFrame(
        dependency_rows,
        schema={
            "dependency_id": pl.String,
            "predecessor_id": pl.String,
            "successor_id": pl.String,
            "dependency_type": pl.String,
            "status": pl.String,
        },
    )
    dependency_by_successor = {row["successor_id"]: row for row in dependency_rows}

    work_items_rows = []
    events_rows = []
    truth_rows = []
    allocated: dict[tuple[str, str], float] = {}

    def add_event(
        *,
        event_id: str,
        entity_id: str,
        event_type: str,
        event_time,
        actor_id: str,
        payload: dict[str, Any],
    ) -> None:
        events_rows.append(
            {
                "event_id": event_id,
                "entity_type": "WorkItem",
                "entity_id": entity_id,
                "event_type": event_type,
                "event_time": event_time,
                "observed_time": event_time + timedelta(days=config.ingestion_delay_days),
                "actor_id": actor_id,
                "payload_json": json.dumps(payload, sort_keys=True),
                "state": payload.get("state", ""),
                "team_id": payload.get("team_id", ""),
                "sprint_id": payload.get("sprint_id", ""),
                "review_rounds": payload.get("review_rounds", 0),
            }
        )

    for index in range(config.work_item_count):
        ordinal = index + 1
        requirement = requirements_rows[index % len(requirements_rows)]
        work_item_id = generate_id("wi", config.seed, ordinal)
        team_id = f"team-{index % config.team_count + 1:03d}"
        sprint_id = f"sprint-{index % config.sprint_count + 1:03d}"
        sprint_start = start + timedelta(days=(index % config.sprint_count) * config.sprint_length_days)
        estimate = float(8 + (index % 6) * 4)
        acceptance_missing = not json.loads(requirement["acceptance_criteria"])
        change = changes_by_requirement.get(requirement["requirement_id"])
        clarification_delay = 2 if acceptance_missing else 0
        scope_delay = 0 if change is None else int(change["added_scope_hours"] // 12)
        dependency = dependency_by_successor.get(work_item_id)
        dependency_delay = 2 if dependency and dependency["status"] == "unresolved" else 0
        queue_delay = 1 if index % 6 == 0 else 0
        review_rounds = 2 if index % 8 == 0 else 1
        review_delay = review_rounds - 1
        blocker_delay = 2 if index % 11 == 0 else 0
        true_delay = (
            clarification_delay
            + scope_delay
            + dependency_delay
            + queue_delay
            + review_delay
            + blocker_delay
        )
        base_duration = max(2, int(round(estimate / 8)))
        planned_start = sprint_start + timedelta(days=1 + index % 3)
        actual_start = planned_start + timedelta(days=queue_delay + dependency_delay)
        actual_complete = actual_start + timedelta(days=base_duration + true_delay)
        committed_date = sprint_start + timedelta(days=config.sprint_length_days - 1)
        allocated[(team_id, sprint_id)] = allocated.get((team_id, sprint_id), 0.0) + estimate
        work_items_rows.append(
            {
                "work_item_id": work_item_id,
                "requirement_id": requirement["requirement_id"],
                "module_id": requirement["module_id"],
                "team_id": team_id,
                "sprint_id": sprint_id,
                "title": f"Implement work item {ordinal}",
                "task_type": ["feature", "bugfix", "test", "integration"][index % 4],
                "status": WorkItemStatus.DONE.value,
                "priority": requirement["priority"],
                "estimate_hours": estimate,
                "committed_date": committed_date,
                "acceptance_criteria_complete": not acceptance_missing,
                "required_skill": skill_sets[index % len(skill_sets)][0],
                "approved": index % 13 != 0,
                "actual_start_at": actual_start,
                "actual_complete_at": actual_complete,
            }
        )
        created = requirement["created_at"] + timedelta(days=1 + index % 3)
        common = {"team_id": team_id, "sprint_id": sprint_id}
        add_event(
            event_id=generate_id("evt", config.seed, ordinal * 10),
            entity_id=work_item_id,
            event_type="WorkItemCreated",
            event_time=created,
            actor_id=requirement["owner"],
            payload={"state": WorkItemStatus.BACKLOG.value, **common},
        )
        add_event(
            event_id=generate_id("evt", config.seed, ordinal * 10 + 1),
            entity_id=work_item_id,
            event_type="WorkItemStarted",
            event_time=actual_start,
            actor_id=requirement["owner"],
            payload={"state": WorkItemStatus.IN_PROGRESS.value, **common},
        )
        if blocker_delay:
            add_event(
                event_id=generate_id("evt", config.seed, ordinal * 10 + 2),
                entity_id=work_item_id,
                event_type="BlockerEvent",
                event_time=actual_start + timedelta(days=1),
                actor_id="system",
                payload={"state": WorkItemStatus.BLOCKED.value, "blocker": "environment", **common},
            )
        add_event(
            event_id=generate_id("evt", config.seed, ordinal * 10 + 3),
            entity_id=work_item_id,
            event_type="WorkItemReviewCompleted",
            event_time=actual_complete - timedelta(days=1),
            actor_id=f"person-{(index + 3) % config.people_count + 1:03d}",
            payload={"state": WorkItemStatus.IN_REVIEW.value, "review_rounds": review_rounds, **common},
        )
        add_event(
            event_id=generate_id("evt", config.seed, ordinal * 10 + 4),
            entity_id=work_item_id,
            event_type="WorkItemCompleted",
            event_time=actual_complete,
            actor_id=requirement["owner"],
            payload={"state": WorkItemStatus.DONE.value, **common},
        )
        truth_rows.append(
            {
                "work_item_id": work_item_id,
                "true_delay_days": true_delay,
                "causal_risk_score": round(min(0.99, 0.10 + true_delay * 0.08 + (0.18 if acceptance_missing else 0.0)), 4),
                "clarification_delay": clarification_delay,
                "scope_delay": scope_delay,
                "dependency_delay": dependency_delay,
                "queue_delay": queue_delay,
                "review_delay": review_delay,
                "blocker_delay": blocker_delay,
            }
        )
    work_items = pl.DataFrame(work_items_rows)

    capacities_rows = []
    for team_index in range(config.team_count):
        team_id = f"team-{team_index + 1:03d}"
        for sprint_index in range(config.sprint_count):
            sprint_id = f"sprint-{sprint_index + 1:03d}"
            capacities_rows.append(
                {
                    "capacity_id": generate_id("cap", config.seed, team_index * config.sprint_count + sprint_index + 1),
                    "team_id": team_id,
                    "sprint_id": sprint_id,
                    "snapshot_at": start + timedelta(days=sprint_index * config.sprint_length_days),
                    "capacity_hours": 320.0,
                    "allocated_hours": round(allocated.get((team_id, sprint_id), 0.0), 2),
                }
            )
    capacities = pl.DataFrame(capacities_rows)
    events = pl.DataFrame(events_rows).sort(["event_time", "event_id"])
    feedback = pl.DataFrame(
        schema={
            "feedback_id": pl.String,
            "target_type": pl.String,
            "target_id": pl.String,
            "feedback_type": pl.String,
            "value_json": pl.String,
            "source": pl.String,
            "created_at": pl.Datetime(time_zone="UTC"),
        }
    )
    return DatasetBundle(
        config=config,
        requirements=requirements,
        changes=changes,
        work_items=work_items,
        events=events,
        dependencies=dependencies,
        sprints=sprints,
        people=people,
        teams=teams,
        capacities=capacities,
        feedback=feedback,
        hidden_truth=pl.DataFrame(truth_rows),
    )


def write_dataset(bundle: DatasetBundle, root: Path) -> None:
    """Write public data and protected truth to separate directories."""
    public_root = root / "public"
    protected_root = root / "_protected"
    public_root.mkdir(parents=True, exist_ok=True)
    protected_root.mkdir(parents=True, exist_ok=True)
    for name, frame in bundle.public_tables.items():
        frame.write_parquet(public_root / f"{name}.parquet")
    bundle.hidden_truth.write_parquet(protected_root / "hidden_truth.parquet")
    (root / "config.json").write_text(
        json.dumps(bundle.config.model_dump(mode="json"), sort_keys=True, indent=2),
        encoding="utf-8",
    )


def load_dataset(root: Path) -> DatasetBundle:
    """Load public tables and protected truth without mixing their columns."""
    config = ProjectConfig.model_validate(json.loads((root / "config.json").read_text(encoding="utf-8")))
    public_root = root / "public"
    return DatasetBundle(
        config=config,
        requirements=pl.read_parquet(public_root / "requirements.parquet"),
        changes=pl.read_parquet(public_root / "changes.parquet"),
        work_items=pl.read_parquet(public_root / "work_items.parquet"),
        events=pl.read_parquet(public_root / "events.parquet"),
        dependencies=pl.read_parquet(public_root / "dependencies.parquet"),
        sprints=pl.read_parquet(public_root / "sprints.parquet"),
        people=pl.read_parquet(public_root / "people.parquet"),
        teams=pl.read_parquet(public_root / "teams.parquet"),
        capacities=pl.read_parquet(public_root / "capacities.parquet"),
        feedback=pl.read_parquet(public_root / "feedback.parquet"),
        hidden_truth=pl.read_parquet(root / "_protected" / "hidden_truth.parquet"),
    )


__all__ = ["DatasetBundle", "generate_dataset", "load_dataset", "write_dataset"]

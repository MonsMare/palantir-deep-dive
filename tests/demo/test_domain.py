from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from software_delivery_demo.domain import (
    ChangeRequest,
    DomainEvent,
    ProjectConfig,
    Requirement,
    WorkItem,
    generate_id,
)


def test_requirement_and_change_request_have_distinct_ids() -> None:
    requirement = Requirement(requirement_id="req-001", title="Export report")
    change = ChangeRequest(change_id="chg-001", requirement_id="req-001")
    assert requirement.requirement_id != change.change_id


def test_domain_event_requires_event_and_observed_time() -> None:
    with pytest.raises(ValidationError):
        DomainEvent(
            event_id="evt-1",
            entity_type="WorkItem",
            entity_id="wi-1",
            event_type="WorkItemStarted",
        )


def test_project_config_has_seed_and_sprint_count() -> None:
    config = ProjectConfig.load(Path("projects/software-delivery-demo/config/project.yaml"))
    assert config.seed == 20260811
    assert config.sprint_count == 8
    assert config.start_date.isoformat() == "2026-01-05"


def test_work_item_defaults_to_backlog_and_event_times_are_aware() -> None:
    work_item = WorkItem(work_item_id="wi-1", title="Implement export")
    assert work_item.status.value == "backlog"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = DomainEvent(
        event_id="evt-1",
        entity_type="WorkItem",
        entity_id="wi-1",
        event_type="WorkItemCreated",
        event_time=now,
        observed_time=now,
        actor_id="person-1",
    )
    assert event.event_time == event.observed_time


def test_generate_id_is_stable_and_namespaced() -> None:
    assert generate_id("req", 20260811, 1) == generate_id("req", 20260811, 1)
    assert generate_id("req", 20260811, 1) != generate_id("chg", 20260811, 1)

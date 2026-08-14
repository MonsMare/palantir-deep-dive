from types import MappingProxyType

import pytest
from pydantic import ValidationError

from aifde.task.contracts import (
    TaskContract,
    TaskContractVersion,
    TaskEvent,
    TaskRecord,
    TaskRun,
)
from aifde.task.lifecycle import (
    ActorAuthority,
    AuthorityPolicy,
    FailureFactKind,
    FixRoundLimitExceeded,
    LifecycleTransitionError,
    TaskLifecycle,
    TaskStatus,
)


def _policy():
    return AuthorityPolicy(
        {
            "agent-1": ActorAuthority.AGENT,
            "human-1": ActorAuthority.HUMAN,
            "system-1": ActorAuthority.SYSTEM,
        }
    )


def _transition_kwargs(**overrides):
    values = {
        "event_id": "event-1",
        "task_id": "linear:LAC-1",
        "actor": "system-1",
        "run_id": "run-1",
        "contract_version": 1,
        "expected_previous_state": TaskStatus.REVIEWING,
        "authority_policy": _policy(),
    }
    values.update(overrides)
    return values


def _contract(**overrides):
    values = {
        "task_id": "linear:LAC-1",
        "project_id": "demo",
        "domain_pack": "software_delivery",
        "task_kind": "forecast",
        "objective": "预测工期",
        "decision_owner": "owner-1",
        "required_outputs": ("ForecastReport",),
        "acceptance": ("每个结论引用证据",),
    }
    values.update(overrides)
    return TaskContract(**values)


def test_review_gate_pass_enters_human_approval():
    assert (
        TaskLifecycle.transition(
            TaskStatus.REVIEWING,
            "gates_pass",
            **_transition_kwargs(),
        )
        == TaskStatus.AWAITING_HUMAN
    )


def test_agent_cannot_approve_a_task():
    with pytest.raises(LifecycleTransitionError, match="agent"):
        TaskLifecycle.transition(
            TaskStatus.AWAITING_HUMAN,
            "authorized_approval",
            **_transition_kwargs(
                event_id="event-approval",
                actor="agent-1",
                expected_previous_state=TaskStatus.AWAITING_HUMAN,
            ),
        )


@pytest.mark.parametrize(
    ("current", "event", "expected_previous_state"),
    [
        (TaskStatus.APPROVED, "action_requested", TaskStatus.APPROVED),
        (TaskStatus.APPROVED, "production_action", TaskStatus.APPROVED),
    ],
)
def test_agent_cannot_request_or_execute_production_action(
    current, event, expected_previous_state
):
    with pytest.raises(LifecycleTransitionError, match="agent"):
        TaskLifecycle.transition(
            current,
            event,
            **_transition_kwargs(
                event_id=f"event-{event}",
                actor="agent-1",
                expected_previous_state=expected_previous_state,
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", ""),
        ("actor", ""),
        ("run_id", ""),
        ("contract_version", None),
        ("expected_previous_state", None),
    ],
)
def test_transition_requires_all_audit_metadata(field, value):
    with pytest.raises((LifecycleTransitionError, ValidationError)):
        TaskLifecycle.transition(
            TaskStatus.REVIEWING,
            "gates_pass",
            **_transition_kwargs(**{field: value}),
        )


def test_transition_rejects_stale_expected_previous_state():
    with pytest.raises(LifecycleTransitionError, match="previous"):
        TaskLifecycle.transition(
            TaskStatus.REVIEWING,
            "gates_pass",
            **_transition_kwargs(expected_previous_state=TaskStatus.RUNNING),
        )


def test_apply_derives_new_state_and_event_cannot_forge_it():
    event = TaskLifecycle.apply(
        TaskStatus.REVIEWING,
        "gates_pass",
        **_transition_kwargs(),
    )

    assert event.previous_state == TaskStatus.REVIEWING
    assert event.expected_previous_state == TaskStatus.REVIEWING
    assert event.new_state == TaskStatus.AWAITING_HUMAN
    assert event.model_dump()["new_state"] == TaskStatus.AWAITING_HUMAN

    with pytest.raises(ValidationError):
        TaskEvent(
            event_id="forged-event",
            task_id="linear:LAC-1",
            event_name="gates_pass",
            actor="system-1",
            authority=ActorAuthority.SYSTEM,
            previous_state=TaskStatus.REVIEWING,
            expected_previous_state=TaskStatus.REVIEWING,
            run_id="run-1",
            contract_version=1,
            fix_round=0,
            new_state=TaskStatus.RELEASED,
        )


def test_apply_rejects_run_and_contract_version_mismatch():
    contract = _contract()
    version = TaskContractVersion(contract=contract, version=1)
    run = TaskRun(
        run_id="run-1",
        contract_version=version,
        status=TaskStatus.REVIEWING,
    )

    with pytest.raises(LifecycleTransitionError, match="contract version"):
        TaskLifecycle.apply(
            TaskStatus.REVIEWING,
            "gates_pass",
            **_transition_kwargs(contract_version=2, run=run),
        )

    with pytest.raises(LifecycleTransitionError, match="run"):
        TaskLifecycle.apply(
            TaskStatus.REVIEWING,
            "gates_pass",
            **_transition_kwargs(run_id="run-2", run=run),
        )


@pytest.mark.parametrize(
    ("current", "event"),
    [
        (TaskStatus.CHECKS_FAILED, "human_reopen"),
        (TaskStatus.FIX_REQUESTED, "redispatch"),
    ],
)
def test_redispatch_increments_fix_round_and_rejects_limit(current, event):
    event_result = TaskLifecycle.apply(
        current,
        event,
        **_transition_kwargs(
            event_id=f"event-{event}",
            actor="human-1",
            expected_previous_state=current,
            fix_round=2,
            max_fix_rounds=3,
        ),
    )
    assert event_result.fix_round == 3

    with pytest.raises(FixRoundLimitExceeded) as error:
        TaskLifecycle.apply(
            current,
            event,
            **_transition_kwargs(
                event_id=f"event-limit-{event}",
                actor="human-1",
                expected_previous_state=current,
                fix_round=3,
                max_fix_rounds=3,
            ),
        )

    assert error.value.failure_fact.kind == FailureFactKind.MAX_FIX_ROUNDS_EXCEEDED
    assert error.value.failure_fact.run_id == "run-1"
    assert error.value.failure_fact.fix_round == 3
    assert error.value.failure_fact.max_fix_rounds == 3


def test_stale_contract_reopen_does_not_consume_fix_round():
    event = TaskLifecycle.apply(
        TaskStatus.STALE,
        "human_reopen",
        **_transition_kwargs(
            event_id="event-stale-reopen",
            actor="human-1",
            expected_previous_state=TaskStatus.STALE,
        ),
    )

    assert event.new_state == TaskStatus.READY
    assert event.fix_round == 0


def test_contract_change_stales_every_active_run_but_preserves_snapshot():
    contract_v1 = _contract()
    version_v1 = TaskContractVersion(contract=contract_v1, version=1)
    active_run = TaskRun(
        run_id="run-active",
        contract_version=version_v1,
        status=TaskStatus.RUNNING,
    )
    review_run = TaskRun(
        run_id="run-review",
        contract_version=version_v1,
        status=TaskStatus.AWAITING_HUMAN,
    )
    released_run = TaskRun(
        run_id="run-released",
        contract_version=version_v1,
        status=TaskStatus.RELEASED,
    )
    record = TaskRecord(
        task_id=contract_v1.task_id,
        contract_version=version_v1,
        status=TaskStatus.RUNNING,
        runs=(active_run, review_run, released_run),
    )
    contract_v2 = _contract(objective="预测工期（修订）")
    version_v2 = TaskContractVersion(contract=contract_v2, version=2)

    updated = TaskLifecycle.update_contract(record, version_v2)

    assert updated.contract_version == version_v2
    assert updated.status == TaskStatus.READY
    assert [run.status for run in updated.runs] == [
        TaskStatus.STALE,
        TaskStatus.STALE,
        TaskStatus.RELEASED,
    ]
    assert updated.runs[0].contract_version == version_v1
    assert record.runs[0].status == TaskStatus.RUNNING


def test_run_contract_version_snapshot_is_immutable_and_record_rejects_mismatch():
    contract_v1 = _contract()
    version_v1 = TaskContractVersion(contract=contract_v1, version=1)
    version_v2 = TaskContractVersion(
        contract=_contract(objective="另一个目标"),
        version=2,
    )
    run = TaskRun(run_id="run-1", contract_version=version_v1)

    with pytest.raises((ValidationError, TypeError)):
        version_v1.version = 2

    with pytest.raises(ValidationError):
        TaskRecord(
            task_id=contract_v1.task_id,
            contract=contract_v1,
            contract_version=version_v2,
            runs=(run,),
        )


def test_transition_table_is_immutable():
    assert isinstance(TaskLifecycle._TRANSITIONS, MappingProxyType)
    with pytest.raises(TypeError):
        TaskLifecycle._TRANSITIONS[(TaskStatus.REVIEWING, "forged")] = TaskStatus.RELEASED

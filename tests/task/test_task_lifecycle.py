from types import MappingProxyType

import pytest
from pydantic import ValidationError

from aifde.task.contracts import (
    TaskContract,
    TaskContractVersion,
    TaskEvent,
    TaskRecord,
)
from aifde.task.lifecycle import (
    ActorAuthority,
    ActorPrincipal,
    FixRoundLimitExceeded,
    LifecycleStateConflictError,
    LifecycleTransitionError,
    TaskLifecycle,
    TaskLifecycleContext,
    TaskRunRegistry,
    TaskStatus,
    TrustedActorResolver,
    UnauthorizedActorError,
)


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


def _context(
    *,
    status=TaskStatus.REVIEWING,
    fix_round=0,
    max_fix_rounds=3,
    run_id="run-1",
    task_id="linear:LAC-1",
):
    contract = _contract(task_id=task_id, max_fix_rounds=max_fix_rounds)
    version = TaskContractVersion(contract=contract, version=1)
    registry = TaskRunRegistry()
    registry.create_run(
        version,
        run_id=run_id,
        status=status,
        fix_round=fix_round,
    )
    resolver = TrustedActorResolver.from_static(
        {
            "agent-1": ActorAuthority.AGENT,
            "human-1": ActorAuthority.HUMAN,
            "system-1": ActorAuthority.SYSTEM,
        }
    )
    lifecycle = TaskLifecycle(
        TaskLifecycleContext(
            run_registry=registry,
            actor_resolver=resolver,
        )
    )
    return lifecycle, registry, resolver, version


def _kwargs(resolver, **overrides):
    values = {
        "event_id": "event-1",
        "actor": resolver.issue("system-1"),
        "expected_previous_state": TaskStatus.REVIEWING,
    }
    values.update(overrides)
    return values


def test_review_gate_pass_enters_human_approval():
    lifecycle, registry, resolver, _version = _context()
    run = registry.get("run-1")

    assert (
        lifecycle.transition(
            run,
            "gates_pass",
            **_kwargs(resolver),
        )
        == TaskStatus.AWAITING_HUMAN
    )


def test_agent_cannot_approve_a_task_even_without_self_reported_authority():
    lifecycle, registry, resolver, _version = _context(
        status=TaskStatus.AWAITING_HUMAN
    )
    run = registry.get("run-1")

    with pytest.raises(UnauthorizedActorError, match="human authority"):
        lifecycle.transition(
            run,
            "authorized_approval",
            **_kwargs(
                resolver,
                event_id="event-approval",
                actor=resolver.issue("agent-1"),
                expected_previous_state=TaskStatus.AWAITING_HUMAN,
            ),
        )


@pytest.mark.parametrize(
    ("current", "event"),
    [
        (TaskStatus.APPROVED, "action_requested"),
        (TaskStatus.APPROVED, "production_action"),
    ],
)
def test_agent_cannot_request_or_execute_production_action(current, event):
    lifecycle, registry, resolver, _version = _context(status=current)
    run = registry.get("run-1")

    with pytest.raises(UnauthorizedActorError, match="human authority"):
        lifecycle.transition(
            run,
            event,
            **_kwargs(
                resolver,
                event_id=f"event-{event}",
                actor=resolver.issue("agent-1"),
                expected_previous_state=current,
            ),
        )


def test_transition_rejects_a_caller_supplied_authority_policy():
    lifecycle, registry, resolver, _version = _context()
    run = registry.get("run-1")

    with pytest.raises(TypeError, match="authority_policy"):
        lifecycle.transition(
            run,
            "gates_pass",
            **_kwargs(
                resolver,
                authority_policy={"agent-1": ActorAuthority.HUMAN},
            ),
        )


def test_trusted_resolver_rejects_agent_identity_bound_as_human():
    with pytest.raises(ValueError, match="agent.*human"):
        TrustedActorResolver.from_static({"agent-1": ActorAuthority.HUMAN})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", ""),
        ("actor", None),
        ("run_id", ""),
        ("contract_version", None),
        ("expected_previous_state", None),
        ("task_id", ""),
    ],
)
def test_transition_requires_all_audit_metadata(field, value):
    lifecycle, registry, resolver, _version = _context()
    run = registry.get("run-1")

    with pytest.raises((LifecycleTransitionError, ValidationError, TypeError)):
        lifecycle.transition(
            run,
            "gates_pass",
            **_kwargs(resolver, **{field: value}),
        )


def test_transition_rejects_stale_expected_previous_state():
    lifecycle, registry, resolver, _version = _context()
    run = registry.get("run-1")

    with pytest.raises(LifecycleStateConflictError, match="previous"):
        lifecycle.transition(
            run,
            "gates_pass",
            **_kwargs(resolver, expected_previous_state=TaskStatus.RUNNING),
        )


def test_transition_requires_a_real_registered_run():
    lifecycle, registry, resolver, version = _context()
    other_registry = TaskRunRegistry()
    other_registry.create_run(version, run_id="run-other", status=TaskStatus.REVIEWING)

    with pytest.raises(LifecycleTransitionError, match="registered run"):
        lifecycle.transition(
            other_registry.get("run-other"),
            "gates_pass",
            **_kwargs(resolver),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", 2),
        ("task_id", "linear:OTHER"),
        ("run_id", "run-2"),
    ],
)
def test_transition_rejects_caller_supplied_run_metadata(field, value):
    lifecycle, registry, resolver, _version = _context()
    run = registry.get("run-1")

    with pytest.raises(TypeError, match=field):
        lifecycle.transition(
            run,
            "gates_pass",
            **_kwargs(resolver, **{field: value}),
        )


def test_transition_rejects_a_forged_task_run_with_matching_metadata():
    lifecycle, registry, resolver, version = _context()
    forged_run = registry.get("run-1").model_copy()
    assert forged_run == registry.get("run-1")
    assert forged_run is not registry.get("run-1")

    with pytest.raises(LifecycleTransitionError, match="registered run"):
        lifecycle.transition(forged_run, "gates_pass", **_kwargs(resolver))


def test_transition_requires_a_run_and_derives_audit_identity_from_it():
    lifecycle, registry, resolver, _version = _context()

    with pytest.raises(TypeError, match="run"):
        lifecycle.transition(
            event="gates_pass",
            **_kwargs(resolver),
        )

    event = lifecycle.apply(registry.get("run-1"), "gates_pass", **_kwargs(resolver))
    assert event.task_id == "linear:LAC-1"
    assert event.run_id == "run-1"
    assert event.contract_version == 1


def test_transition_requires_run_state_to_match_current_and_rejects_stale():
    lifecycle, registry, resolver, _version = _context(status=TaskStatus.RUNNING)

    with pytest.raises(LifecycleStateConflictError, match="run state"):
        lifecycle.transition(
            registry.get("run-1"),
            "gates_pass",
            **_kwargs(resolver),
        )

    stale_lifecycle, _stale_registry, stale_resolver, _stale_version = _context(
        status=TaskStatus.STALE
    )
    with pytest.raises(LifecycleTransitionError, match="stale"):
        stale_lifecycle.transition(
            _stale_registry.get("run-1"),
            "human_reopen",
            **_kwargs(
                stale_resolver,
                actor=stale_resolver.issue("human-1"),
                expected_previous_state=TaskStatus.STALE,
            ),
        )


def test_apply_derives_new_state_and_only_lifecycle_can_create_task_event():
    lifecycle, registry, resolver, _version = _context()
    event = lifecycle.apply(
        registry.get("run-1"),
        "gates_pass",
        **_kwargs(resolver),
    )

    assert event.previous_state == TaskStatus.REVIEWING
    assert event.expected_previous_state == TaskStatus.REVIEWING
    assert event.new_state == TaskStatus.AWAITING_HUMAN
    assert event.model_dump()["new_state"] == TaskStatus.AWAITING_HUMAN
    assert event.authority is ActorAuthority.SYSTEM

    with pytest.raises(TypeError, match="lifecycle"):
        TaskEvent(
            event_id="forged-event",
            task_id="linear:LAC-1",
            event_name="authorized_approval",
            actor="agent-1",
            authority=ActorAuthority.HUMAN,
            previous_state=TaskStatus.AWAITING_HUMAN,
            expected_previous_state=TaskStatus.AWAITING_HUMAN,
            run_id="run-1",
            contract_version=1,
            fix_round=0,
        )

    with pytest.raises(TypeError, match="lifecycle"):
        ActorPrincipal("human-1")

    principal = resolver.issue("system-1")
    with pytest.raises(AttributeError, match="immutable"):
        principal._authority = ActorAuthority.HUMAN

    with pytest.raises(TypeError, match="lifecycle"):
        TaskEvent.model_construct(
            event_id="forged-construct",
            task_id="linear:LAC-1",
            event_name="authorized_approval",
            actor="agent-1",
            authority=ActorAuthority.HUMAN,
            previous_state=TaskStatus.AWAITING_HUMAN,
            expected_previous_state=TaskStatus.AWAITING_HUMAN,
            run_id="run-1",
            contract_version=1,
            fix_round=0,
        )

    with pytest.raises(TypeError, match="lifecycle"):
        event.model_copy(
            update={"actor": "agent-1", "authority": ActorAuthority.HUMAN}
        )


def test_registry_persists_derived_state_and_fix_round():
    lifecycle, registry, resolver, _version = _context(
        status=TaskStatus.FIX_REQUESTED,
        fix_round=2,
    )

    event = lifecycle.apply(
        registry.get("run-1"),
        "redispatch",
        **_kwargs(
            resolver,
            actor=resolver.issue("system-1"),
            expected_previous_state=TaskStatus.FIX_REQUESTED,
        ),
    )

    run = registry.get("run-1")
    assert event.new_state == TaskStatus.RUNNING
    assert run.status == TaskStatus.RUNNING
    assert run.fix_round == 3


def test_fix_round_and_max_are_derived_from_trusted_run_and_contract():
    lifecycle, registry, resolver, _version = _context(
        status=TaskStatus.FIX_REQUESTED,
        fix_round=0,
        max_fix_rounds=1,
    )

    with pytest.raises(TypeError, match="fix_round"):
        lifecycle.transition(
            registry.get("run-1"),
            "redispatch",
            **_kwargs(
                resolver,
                actor=resolver.issue("system-1"),
                expected_previous_state=TaskStatus.FIX_REQUESTED,
                fix_round=0,
                max_fix_rounds=999,
            ),
        )


@pytest.mark.parametrize(
    ("status", "event"),
    [
        (TaskStatus.CHECKS_FAILED, "human_reopen"),
        (TaskStatus.REVIEWING, "major_or_blocker"),
        (TaskStatus.FIX_REQUESTED, "redispatch"),
    ],
)
def test_fix_round_limit_is_enforced_without_caller_override(status, event):
    lifecycle, registry, resolver, _version = _context(
        status=status,
        fix_round=1,
        max_fix_rounds=1,
    )

    with pytest.raises(FixRoundLimitExceeded) as error:
        lifecycle.apply(
            registry.get("run-1"),
            event,
            **_kwargs(
                resolver,
                actor=resolver.issue("human-1"),
                expected_previous_state=status,
            ),
        )

    fact = error.value.failure_fact
    assert fact.run_id == "run-1"
    assert fact.contract_version == 1
    assert fact.fix_round == 1
    assert fact.max_fix_rounds == 1
    assert registry.get("run-1").failure_facts[-1] == fact


def test_contract_change_stales_registry_runs_and_preserves_run_snapshots():
    lifecycle, registry, resolver, version_v1 = _context(status=TaskStatus.RUNNING)
    registry.create_run(
        version_v1,
        run_id="run-released",
        status=TaskStatus.RELEASED,
    )
    record = TaskRecord(
        task_id=version_v1.contract.task_id,
        contract_version=version_v1,
        status=TaskStatus.RUNNING,
        runs=(registry.get("run-1"), registry.get("run-released")),
    )
    version_v2 = TaskContractVersion(
        contract=_contract(objective="预测工期（修订）"),
        version=2,
    )

    updated = lifecycle.update_contract(record, version_v2)

    assert updated.status == TaskStatus.READY
    assert registry.get("run-1").status == TaskStatus.STALE
    assert registry.get("run-released").status == TaskStatus.RELEASED
    assert registry.get("run-1").contract_version == version_v1
    assert resolver.issue("system-1").actor_id == "system-1"


def test_run_contract_snapshot_is_immutable_and_fix_round_cannot_exceed_contract():
    contract = _contract(max_fix_rounds=1)
    version = TaskContractVersion(contract=contract, version=1)
    registry = TaskRunRegistry()

    with pytest.raises(ValidationError):
        registry.create_run(version, run_id="run-bad", fix_round=2)

    run = registry.create_run(version, run_id="run-1")
    with pytest.raises((ValidationError, TypeError)):
        version.version = 2
    assert run.contract_version == version


def test_transition_table_is_immutable():
    assert isinstance(TaskLifecycle._TRANSITIONS, MappingProxyType)
    with pytest.raises(TypeError):
        TaskLifecycle._TRANSITIONS[(TaskStatus.REVIEWING, "forged")] = TaskStatus.RELEASED

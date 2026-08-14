"""Governed, deterministic task lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value.strip()


class TaskStatus(str, Enum):
    INTAKE = "intake"
    NEEDS_INFO = "needs_info"
    READY = "ready"
    RUNNING = "running"
    CHECKS_FAILED = "checks_failed"
    REVIEWING = "reviewing"
    FIX_REQUESTED = "fix_requested"
    AWAITING_HUMAN = "awaiting_human"
    APPROVED = "approved"
    ACTION_PENDING = "action_pending"
    RELEASED = "released"
    STALE = "stale"
    CANCELED = "canceled"


class ActorAuthority(str, Enum):
    """The authority class resolved for an authenticated actor."""

    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"


class FailureFactKind(str, Enum):
    """Stable failure fact kinds that downstream projections can handle."""

    MAX_FIX_ROUNDS_EXCEEDED = "max_fix_rounds_exceeded"


class FailureFact(BaseModel):
    """A typed, immutable fact emitted when a fix loop is exhausted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: FailureFactKind
    task_id: str
    run_id: str
    contract_version: int = Field(ge=1)
    fix_round: int = Field(ge=0)
    max_fix_rounds: int = Field(ge=0)
    reason: str

    @field_validator("task_id", "run_id", "reason")
    @classmethod
    def require_nonblank(cls, value: str, info: Any) -> str:
        return _require_nonblank(value, info.field_name)


@dataclass(frozen=True, slots=True)
class AuthorityPolicy:
    """Immutable actor-to-authority directory and lifecycle authorization policy."""

    actor_authorities: Mapping[str, ActorAuthority]

    def __init__(self, actor_authorities: Mapping[str, ActorAuthority]):
        if not isinstance(actor_authorities, Mapping) or not actor_authorities:
            raise ValueError("actor_authorities must not be empty")

        normalized: dict[str, ActorAuthority] = {}
        for actor, authority in actor_authorities.items():
            actor_id = _require_nonblank(actor, "actor")
            try:
                resolved_authority = ActorAuthority(authority)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown actor authority: {authority!r}") from exc
            if actor_id in normalized:
                raise ValueError(f"duplicate actor binding: {actor_id!r}")
            normalized[actor_id] = resolved_authority

        object.__setattr__(self, "actor_authorities", MappingProxyType(normalized))

    def authority_for(self, actor: str) -> ActorAuthority:
        try:
            actor_id = _require_nonblank(actor, "actor")
        except ValueError as exc:
            raise UnauthorizedActorError("actor must not be empty") from exc
        try:
            return self.actor_authorities[actor_id]
        except KeyError as exc:
            raise UnauthorizedActorError(f"actor is not bound by authority policy: {actor_id!r}") from exc

    def authorize(self, actor: str, event: str) -> ActorAuthority:
        authority = self.authority_for(actor)
        TaskLifecycle._validate_authority(authority, event)
        return authority


class LifecycleTransitionError(ValueError):
    """Raised when a lifecycle event is invalid or violates governance."""


class UnauthorizedActorError(LifecycleTransitionError):
    """Raised when an actor lacks authority for a lifecycle event."""


class LifecycleStateConflictError(LifecycleTransitionError):
    """Raised when the caller's expected state is not the current state."""


class FixRoundLimitExceeded(LifecycleTransitionError):
    """Raised when redispatch would exceed the contract's fix-round limit."""

    def __init__(self, failure_fact: FailureFact):
        self.failure_fact = failure_fact
        super().__init__(
            "max fix rounds exceeded for "
            f"run {failure_fact.run_id!r}: "
            f"{failure_fact.fix_round}/{failure_fact.max_fix_rounds}"
        )


class TaskLifecycle:
    """The sole state-transition kernel for governed tasks."""

    _TRANSITIONS: ClassVar[Mapping[tuple[TaskStatus, str], TaskStatus]] = MappingProxyType(
        {
            (TaskStatus.INTAKE, "contract_invalid"): TaskStatus.NEEDS_INFO,
            (TaskStatus.INTAKE, "contract_valid"): TaskStatus.READY,
            (TaskStatus.NEEDS_INFO, "human_updates"): TaskStatus.INTAKE,
            (TaskStatus.READY, "dispatch"): TaskStatus.RUNNING,
            (TaskStatus.RUNNING, "executor_or_checks_fail"): TaskStatus.CHECKS_FAILED,
            (TaskStatus.RUNNING, "implementation_done"): TaskStatus.REVIEWING,
            (TaskStatus.CHECKS_FAILED, "human_reopen"): TaskStatus.READY,
            (TaskStatus.REVIEWING, "major_or_blocker"): TaskStatus.FIX_REQUESTED,
            (TaskStatus.REVIEWING, "gates_pass"): TaskStatus.AWAITING_HUMAN,
            (TaskStatus.FIX_REQUESTED, "redispatch"): TaskStatus.RUNNING,
            (TaskStatus.AWAITING_HUMAN, "authorized_approval"): TaskStatus.APPROVED,
            (TaskStatus.AWAITING_HUMAN, "human_revision"): TaskStatus.READY,
            (TaskStatus.APPROVED, "action_requested"): TaskStatus.ACTION_PENDING,
            (TaskStatus.APPROVED, "no_action"): TaskStatus.RELEASED,
            (TaskStatus.ACTION_PENDING, "action_reconciled"): TaskStatus.RELEASED,
            (TaskStatus.ACTION_PENDING, "approval_required"): TaskStatus.AWAITING_HUMAN,
            (TaskStatus.RUNNING, "timeout_or_contract_change"): TaskStatus.STALE,
            (TaskStatus.REVIEWING, "timeout_or_contract_change"): TaskStatus.STALE,
            (TaskStatus.STALE, "human_reopen"): TaskStatus.READY,
            (TaskStatus.INTAKE, "human_cancel"): TaskStatus.CANCELED,
            (TaskStatus.READY, "human_cancel"): TaskStatus.CANCELED,
            (TaskStatus.RUNNING, "authorized_cancel"): TaskStatus.CANCELED,
        }
    )

    _HUMAN_ONLY_EVENTS: ClassVar[frozenset[str]] = frozenset(
        {
            "authorized_approval",
            "action_requested",
            "no_action",
            "human_updates",
            "human_reopen",
            "human_revision",
            "human_cancel",
            "authorized_cancel",
            "production_action",
        }
    )
    _SYSTEM_ONLY_EVENTS: ClassVar[frozenset[str]] = frozenset(
        {
            "contract_invalid",
            "contract_valid",
            "action_reconciled",
            "approval_required",
            "timeout_or_contract_change",
        }
    )
    _FIX_ROUND_TRANSITIONS: ClassVar[frozenset[tuple[TaskStatus, str]]] = frozenset(
        {
            (TaskStatus.CHECKS_FAILED, "human_reopen"),
            (TaskStatus.FIX_REQUESTED, "redispatch"),
        }
    )

    @staticmethod
    def _status(value: TaskStatus, field_name: str) -> TaskStatus:
        try:
            return TaskStatus(value)
        except (TypeError, ValueError) as exc:
            raise LifecycleTransitionError(f"unknown {field_name}: {value!r}") from exc

    @classmethod
    def _validate_authority(cls, authority: ActorAuthority, event: str) -> None:
        if not isinstance(event, str) or not event.strip():
            raise LifecycleTransitionError(f"event must not be empty: {event!r}")
        try:
            resolved_authority = ActorAuthority(authority)
        except (TypeError, ValueError) as exc:
            raise UnauthorizedActorError(f"unknown actor authority: {authority!r}") from exc

        if event in cls._HUMAN_ONLY_EVENTS and resolved_authority is not ActorAuthority.HUMAN:
            raise UnauthorizedActorError(
                f"event {event!r} requires human authority; "
                f"resolved authority is {resolved_authority.value!r}"
            )
        if event in cls._SYSTEM_ONLY_EVENTS and resolved_authority is not ActorAuthority.SYSTEM:
            raise UnauthorizedActorError(
                f"event {event!r} requires system authority; "
                f"resolved authority is {resolved_authority.value!r}"
            )

    @classmethod
    def _derive(cls, current: TaskStatus, event: str) -> TaskStatus:
        current_status = cls._status(current, "current task status")
        if not isinstance(event, str) or not event.strip():
            raise LifecycleTransitionError(f"unknown lifecycle event: {event!r}")
        try:
            return cls._TRANSITIONS[(current_status, event)]
        except KeyError as exc:
            raise LifecycleTransitionError(
                f"illegal lifecycle transition from {current_status.value!r} using {event!r}"
            ) from exc

    @classmethod
    def apply(
        cls,
        current: TaskStatus,
        event: str,
        *,
        event_id: str,
        actor: str,
        run_id: str,
        contract_version: int,
        expected_previous_state: TaskStatus,
        authority_policy: AuthorityPolicy | None = None,
        policy: AuthorityPolicy | None = None,
        task_id: str = "task",
        fix_round: int | None = None,
        max_fix_rounds: int | None = None,
        run: Any | None = None,
    ) -> Any:
        """Validate and apply one audited transition, returning its immutable event.

        The returned ``TaskEvent.new_state`` is computed from the immutable table;
        callers cannot provide or override it.  ``run`` is optional for the pure
        kernel, but when supplied its id and contract snapshot are checked against
        the audited transition metadata.
        """

        if authority_policy is not None and policy is not None and authority_policy != policy:
            raise LifecycleTransitionError("authority_policy and policy disagree")
        resolved_policy = authority_policy or policy
        if resolved_policy is None:
            raise LifecycleTransitionError("authority_policy is required")
        if not isinstance(resolved_policy, AuthorityPolicy):
            raise LifecycleTransitionError("authority_policy must be an AuthorityPolicy")

        for field_name, value in (
            ("event_id", event_id),
            ("actor", actor),
            ("run_id", run_id),
            ("task_id", task_id),
            ("event", event),
        ):
            try:
                normalized_value = _require_nonblank(value, field_name)
            except ValueError as exc:
                raise LifecycleTransitionError(str(exc)) from exc
            if field_name == "event_id":
                event_id = normalized_value
            elif field_name == "actor":
                actor = normalized_value
            elif field_name == "run_id":
                run_id = normalized_value
            elif field_name == "task_id":
                task_id = normalized_value
            else:
                event = normalized_value

        current_status = cls._status(current, "current task status")
        expected_status = cls._status(expected_previous_state, "expected previous state")
        if current_status is not expected_status:
            raise LifecycleStateConflictError(
                "expected previous state "
                f"{expected_status.value!r} does not match current state "
                f"{current_status.value!r}"
            )

        if not isinstance(contract_version, int) or isinstance(contract_version, bool) or contract_version < 1:
            raise LifecycleTransitionError("contract version must be a positive integer")

        authority = resolved_policy.authorize(actor, event)

        if run is not None:
            if run.run_id != run_id:
                raise LifecycleStateConflictError(
                    f"run metadata does not match supplied run: {run_id!r}"
                )
            if run.contract_version.version != contract_version:
                raise LifecycleStateConflictError(
                    "contract version does not match the run snapshot: "
                    f"{contract_version!r}"
                )
            if run.contract_version.contract.task_id != task_id:
                raise LifecycleStateConflictError(
                    "task id does not match the run contract snapshot"
                )
            if run.status is TaskStatus.STALE:
                raise LifecycleTransitionError("stale runs cannot submit lifecycle events")

        if fix_round is None:
            current_fix_round = 0
        elif not isinstance(fix_round, int) or isinstance(fix_round, bool) or fix_round < 0:
            raise LifecycleTransitionError("fix_round must be a non-negative integer")
        else:
            current_fix_round = fix_round

        if max_fix_rounds is not None and (
            not isinstance(max_fix_rounds, int)
            or isinstance(max_fix_rounds, bool)
            or max_fix_rounds < 0
        ):
            raise LifecycleTransitionError("max_fix_rounds must be a non-negative integer")

        if (current_status, event) in cls._FIX_ROUND_TRANSITIONS:
            if fix_round is None:
                raise LifecycleTransitionError(
                    f"fix_round is required for {event!r}"
                )
            if max_fix_rounds is None:
                raise LifecycleTransitionError(
                    f"max_fix_rounds is required for {event!r}"
                )
            if current_fix_round >= max_fix_rounds:
                failure_fact = FailureFact(
                    kind=FailureFactKind.MAX_FIX_ROUNDS_EXCEEDED,
                    task_id=task_id,
                    run_id=run_id,
                    contract_version=contract_version,
                    fix_round=current_fix_round,
                    max_fix_rounds=max_fix_rounds,
                    reason="redispatch rejected after the contract fix-round limit",
                )
                raise FixRoundLimitExceeded(failure_fact)
            recorded_fix_round = current_fix_round + 1
        else:
            recorded_fix_round = current_fix_round

        next_state = cls._derive(current_status, event)

        from .contracts import TaskEvent

        return TaskEvent(
            event_id=event_id,
            task_id=task_id,
            event_name=event,
            actor=actor,
            authority=authority,
            previous_state=current_status,
            expected_previous_state=expected_status,
            run_id=run_id,
            contract_version=contract_version,
            fix_round=recorded_fix_round,
        )

    @classmethod
    def transition(
        cls,
        current: TaskStatus,
        event: str,
        *,
        event_id: str,
        actor: str,
        run_id: str,
        contract_version: int,
        expected_previous_state: TaskStatus,
        authority_policy: AuthorityPolicy | None = None,
        policy: AuthorityPolicy | None = None,
        task_id: str = "task",
        fix_round: int | None = None,
        max_fix_rounds: int | None = None,
        run: Any | None = None,
    ) -> TaskStatus:
        """Apply a governed transition and return only its derived next status."""

        return cls.apply(
            current,
            event,
            event_id=event_id,
            actor=actor,
            run_id=run_id,
            contract_version=contract_version,
            expected_previous_state=expected_previous_state,
            authority_policy=authority_policy,
            policy=policy,
            task_id=task_id,
            fix_round=fix_round,
            max_fix_rounds=max_fix_rounds,
            run=run,
        ).new_state

    @staticmethod
    def update_contract(record: Any, contract_version: Any) -> Any:
        """Install a new contract version and stale every active run."""

        try:
            return record.with_contract(contract_version)
        except AttributeError as exc:
            raise TypeError("record must be a TaskRecord") from exc

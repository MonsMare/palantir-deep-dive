"""Governed task lifecycle transitions and their trust boundaries.

The lifecycle kernel deliberately separates caller data from trusted facts:

* a transition accepts an immutable ``TaskRun`` snapshot issued by the bound
  ``TaskRunRegistry``; ids and contract metadata are derived from that snapshot;
* an actor must be a ``TrustedPrincipal`` issued by the resolver installed in
  the ``TaskLifecycleContext``; callers cannot attach an authority mapping to a
  transition; and
* the registry replaces the consumed snapshot only after the transition event
  has been constructed, so a copied or stale snapshot cannot be replayed.

This is an in-process trust boundary.  Resolver construction and registry
ownership belong to the application bootstrap/lifecycle adapter, not to an
agent or an external comment payload.
"""

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


class LifecycleTransitionError(ValueError):
    """Raised when a lifecycle event is invalid or violates governance."""


class UnauthorizedActorError(LifecycleTransitionError):
    """Raised when an actor lacks authority for a lifecycle event."""


class LifecycleStateConflictError(LifecycleTransitionError):
    """Raised when a snapshot and its expected state do not match."""


class FailureFactKind(str, Enum):
    """Stable failure fact kinds that downstream projections can handle."""

    MAX_FIX_ROUNDS_EXCEEDED = "max_fix_rounds_exceeded"


class FailureFact(BaseModel):
    """An immutable fact emitted when a fix loop is exhausted."""

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


_PRINCIPAL_TOKEN = object()
_RESOLVER_TOKEN = object()
_LIFECYCLE_MUTATION_TOKEN = object()


class ActorPrincipal:
    """Opaque actor identity issued by a trusted ``TrustedActorResolver``.

    Direct construction is rejected intentionally.  A string plus a claimed
    authority is not an authentication result and must never be enough to
    approve a task or request production work.
    """

    __slots__ = ("_actor_id", "_authority", "_resolver_identity", "_sealed")

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("ActorPrincipal is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        actor_id: str,
        authority: ActorAuthority | None = None,
        *,
        _token: object | None = None,
        _resolver_identity: object | None = None,
    ) -> None:
        if _token is not _PRINCIPAL_TOKEN:
            raise TypeError(
                "ActorPrincipal can only be issued by the trusted lifecycle resolver"
            )
        self._actor_id = _require_nonblank(actor_id, "actor")
        try:
            self._authority = ActorAuthority(authority)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unknown actor authority: {authority!r}") from exc
        self._resolver_identity = _resolver_identity
        object.__setattr__(self, "_sealed", True)

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def authority(self) -> ActorAuthority:
        return self._authority

    def __repr__(self) -> str:
        return (
            f"ActorPrincipal(actor_id={self._actor_id!r}, "
            f"authority={self._authority.value!r})"
        )


TrustedPrincipal = ActorPrincipal


class TrustedActorResolver:
    """Immutable actor directory installed at the lifecycle trust boundary.

    ``from_static`` is a bootstrap operation.  It is intentionally not
    accepted by ``TaskLifecycle.transition``; a transition only accepts a
    principal issued by the resolver bound to its context.  In particular,
    an identity conventionally named as an agent cannot be configured as a
    human authority, preventing the common self-escalation test case.
    """

    __slots__ = ("_actor_authorities", "_identity")

    def __init__(
        self,
        actor_authorities: Mapping[str, ActorAuthority],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _RESOLVER_TOKEN:
            raise TypeError(
                "TrustedActorResolver must be created through from_static"
            )
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
            if (
                resolved_authority is ActorAuthority.HUMAN
                and actor_id.casefold().startswith("agent")
            ):
                raise ValueError(
                    "agent identities cannot be bound to human authority"
                )
            normalized[actor_id] = resolved_authority

        self._actor_authorities = MappingProxyType(normalized)
        self._identity = object()

    @classmethod
    def from_static(
        cls, actor_authorities: Mapping[str, ActorAuthority]
    ) -> "TrustedActorResolver":
        """Create the resolver during trusted application bootstrap."""

        return cls(actor_authorities, _token=_RESOLVER_TOKEN)

    def issue(self, actor: str) -> ActorPrincipal:
        actor_id = _require_nonblank(actor, "actor")
        try:
            authority = self._actor_authorities[actor_id]
        except KeyError as exc:
            raise UnauthorizedActorError(
                f"actor is not bound by the trusted resolver: {actor_id!r}"
            ) from exc
        return ActorPrincipal(
            actor_id,
            authority,
            _token=_PRINCIPAL_TOKEN,
            _resolver_identity=self._identity,
        )

    def resolve(self, principal: ActorPrincipal) -> ActorAuthority:
        if type(principal) is not ActorPrincipal:
            raise UnauthorizedActorError(
                "actor must be a TrustedPrincipal issued by the lifecycle resolver"
            )
        if principal._resolver_identity is not self._identity:
            raise UnauthorizedActorError(
                "actor principal was not issued by this lifecycle resolver"
            )
        try:
            authority = self._actor_authorities[principal.actor_id]
        except KeyError as exc:
            raise UnauthorizedActorError(
                f"actor is not bound by the trusted resolver: {principal.actor_id!r}"
            ) from exc
        if principal.authority is not authority:
            raise UnauthorizedActorError("actor principal authority does not match binding")
        return authority


@dataclass(frozen=True, slots=True)
class AuthorityPolicy:
    """Legacy immutable directory kept for import compatibility.

    It is not a transition input.  New lifecycle code must bind a
    ``TrustedActorResolver`` in ``TaskLifecycleContext`` so a caller cannot
    swap policy mappings on individual calls.
    """

    actor_authorities: Mapping[str, ActorAuthority]

    def __init__(self, actor_authorities: Mapping[str, ActorAuthority]):
        resolver = TrustedActorResolver.from_static(actor_authorities)
        object.__setattr__(self, "actor_authorities", resolver._actor_authorities)

    def authority_for(self, actor: str) -> ActorAuthority:
        actor_id = _require_nonblank(actor, "actor")
        try:
            return self.actor_authorities[actor_id]
        except KeyError as exc:
            raise UnauthorizedActorError(
                f"actor is not bound by authority policy: {actor_id!r}"
            ) from exc

    def authorize(self, actor: str, event: str) -> ActorAuthority:
        authority = self.authority_for(actor)
        TaskLifecycle._validate_authority(authority, event)
        return authority


class FixRoundLimitExceeded(LifecycleTransitionError):
    """Raised when a new fix round would exceed the contract limit."""

    def __init__(self, failure_fact: FailureFact):
        self.failure_fact = failure_fact
        super().__init__(
            "max fix rounds exceeded for "
            f"run {failure_fact.run_id!r}: "
            f"{failure_fact.fix_round}/{failure_fact.max_fix_rounds}"
        )


class TaskRunRegistry:
    """Registry that issues and consumes immutable run snapshots.

    The registry proves provenance by object identity: a copied or newly
    constructed ``TaskRun`` with matching fields is not a registered snapshot.
    Every successful transition replaces the consumed object, making the old
    snapshot unusable for replay.  The registry is therefore the source of
    run id, contract version, current state, active/stale status and fix round.
    """

    def __init__(self) -> None:
        self._runs: dict[str, Any] = {}

    def create_run(
        self,
        contract_version: Any,
        *,
        run_id: str,
        status: TaskStatus = TaskStatus.READY,
        fix_round: int = 0,
    ) -> Any:
        from .contracts import TaskContractVersion, TaskRun

        if not isinstance(contract_version, TaskContractVersion):
            raise TypeError("contract_version must be a TaskContractVersion")
        normalized_run_id = _require_nonblank(run_id, "run_id")
        if normalized_run_id in self._runs:
            raise LifecycleTransitionError(
                f"run is already registered: {normalized_run_id!r}"
            )
        run = TaskRun(
            run_id=normalized_run_id,
            contract_version=contract_version,
            status=status,
            fix_round=fix_round,
        )
        self._runs[normalized_run_id] = run
        return run

    def get(self, run_id: str) -> Any:
        normalized_run_id = _require_nonblank(run_id, "run_id")
        try:
            return self._runs[normalized_run_id]
        except KeyError as exc:
            raise LifecycleTransitionError(
                f"run is not registered: {normalized_run_id!r}"
            ) from exc

    def is_registered(self, run: Any) -> bool:
        from .contracts import TaskRun

        return (
            type(run) is TaskRun
            and self._runs.get(run.run_id) is run
        )

    def require_registered(self, run: Any) -> Any:
        if not self.is_registered(run):
            raise LifecycleTransitionError(
                "transition requires a registered run snapshot"
            )
        return run

    def require_record(self, record: Any) -> Any:
        from .contracts import TaskRecord

        if type(record) is not TaskRecord:
            raise TypeError("record must be a TaskRecord")

        for run in record.runs:
            self.require_registered(run)
            if run.is_active and run.contract_version != record.contract_version:
                raise LifecycleStateConflictError(
                    "active run contract version does not match the task record"
                )
        return record

    def commit_transition(
        self,
        run: Any,
        *,
        new_state: TaskStatus,
        fix_round: int,
        _lifecycle_token: object | None = None,
    ) -> Any:
        from .contracts import TaskRun

        if _lifecycle_token is not _LIFECYCLE_MUTATION_TOKEN:
            raise TypeError(
                "registry transitions can only be committed by the lifecycle"
            )
        self.require_registered(run)
        if not run.is_active:
            raise LifecycleTransitionError(
                f"stale or inactive run cannot transition: {run.run_id!r}"
            )
        if not isinstance(new_state, TaskStatus):
            raise TypeError("new_state must be a TaskStatus")
        if not isinstance(fix_round, int) or isinstance(fix_round, bool) or fix_round < 0:
            raise ValueError("fix_round must be a non-negative integer")
        if fix_round > run.contract_version.contract.max_fix_rounds:
            raise ValueError("fix_round exceeds the contract max_fix_rounds")
        if fix_round not in (run.fix_round, run.fix_round + 1):
            raise LifecycleStateConflictError(
                "fix_round must be derived from the current run snapshot"
            )

        updated = run.model_copy(
            update={"status": new_state, "fix_round": fix_round}
        )
        if not isinstance(updated, TaskRun):
            raise TypeError("registry could not produce a TaskRun snapshot")
        self._runs[run.run_id] = updated
        return updated

    def record_failure(
        self,
        run: Any,
        failure_fact: FailureFact,
        *,
        _lifecycle_token: object | None = None,
    ) -> Any:
        if _lifecycle_token is not _LIFECYCLE_MUTATION_TOKEN:
            raise TypeError(
                "failure facts can only be recorded by the lifecycle"
            )
        self.require_registered(run)
        if failure_fact.run_id != run.run_id:
            raise LifecycleStateConflictError("failure fact run does not match snapshot")
        if failure_fact.task_id != run.task_id:
            raise LifecycleStateConflictError("failure fact task does not match snapshot")
        if failure_fact.contract_version != run.contract_version.version:
            raise LifecycleStateConflictError(
                "failure fact contract version does not match the run snapshot"
            )
        if failure_fact.fix_round != run.fix_round:
            raise LifecycleStateConflictError(
                "failure fact fix round does not match the run snapshot"
            )
        if (
            failure_fact.kind is not FailureFactKind.MAX_FIX_ROUNDS_EXCEEDED
            or failure_fact.max_fix_rounds
            != run.contract_version.contract.max_fix_rounds
        ):
            raise LifecycleStateConflictError(
                "failure fact does not match the run contract limit"
            )
        updated = run.model_copy(
            update={"failure_facts": (*run.failure_facts, failure_fact)}
        )
        self._runs[run.run_id] = updated
        return updated

    def stale_active_runs(
        self,
        task_id: str,
        *,
        _lifecycle_token: object | None = None,
    ) -> tuple[Any, ...]:
        if _lifecycle_token is not _LIFECYCLE_MUTATION_TOKEN:
            raise TypeError(
                "run invalidation can only be performed by the lifecycle"
            )
        normalized_task_id = _require_nonblank(task_id, "task_id")
        stale_runs: list[Any] = []
        for run_id, run in tuple(self._runs.items()):
            if run.task_id != normalized_task_id or not run.is_active:
                continue
            updated = run.model_copy(update={"status": TaskStatus.STALE})
            self._runs[run_id] = updated
            stale_runs.append(updated)
        return tuple(stale_runs)


@dataclass(frozen=True, slots=True)
class TaskLifecycleContext:
    """Trusted dependencies shared by one lifecycle kernel instance."""

    run_registry: TaskRunRegistry
    actor_resolver: TrustedActorResolver

    def __post_init__(self) -> None:
        if not isinstance(self.run_registry, TaskRunRegistry):
            raise TypeError("run_registry must be a TaskRunRegistry")
        if not isinstance(self.actor_resolver, TrustedActorResolver):
            raise TypeError("actor_resolver must be a TrustedActorResolver")


class TaskLifecycle:
    """The sole state-transition kernel for governed tasks.

    ``transition`` and ``apply`` intentionally have no ``run_id``,
    ``contract_version``, ``task_id``, authority policy, or fix-round
    parameters.  Those facts are read from the registered ``TaskRun`` passed
    to the call, and the caller must present an actor principal issued by the
    context's resolver.
    """

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
            "major_or_blocker",
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
            "gates_pass",
        }
    )
    _FIX_ROUND_TRANSITIONS: ClassVar[frozenset[tuple[TaskStatus, str]]] = frozenset(
        {
            (TaskStatus.CHECKS_FAILED, "human_reopen"),
            (TaskStatus.REVIEWING, "major_or_blocker"),
            (TaskStatus.FIX_REQUESTED, "redispatch"),
        }
    )

    def __init__(self, context: TaskLifecycleContext) -> None:
        if not isinstance(context, TaskLifecycleContext):
            raise TypeError("TaskLifecycle requires a TaskLifecycleContext")
        self._context = context

    @property
    def context(self) -> TaskLifecycleContext:
        return self._context

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

    def _trusted_run(self, run: Any) -> Any:
        registered_run = self._context.run_registry.require_registered(run)
        if not registered_run.is_active:
            raise LifecycleTransitionError(
                f"stale or inactive run cannot submit lifecycle events: {run.run_id!r}"
            )
        return registered_run

    def apply(
        self,
        run: Any,
        event: str,
        *,
        event_id: str,
        actor: ActorPrincipal,
        expected_previous_state: TaskStatus,
    ) -> Any:
        """Validate, persist and return one event from a trusted run snapshot.

        ``run_id``, ``task_id``, ``contract_version``, ``fix_round`` and
        ``max_fix_rounds`` are deliberately absent from this API.  Supplying
        any of them is a ``TypeError`` rather than an opportunity to override
        the registry or contract snapshot.
        """

        from .contracts import TaskEvent

        trusted_run = self._trusted_run(run)
        try:
            normalized_event_id = _require_nonblank(event_id, "event_id")
            normalized_event = _require_nonblank(event, "event")
        except ValueError as exc:
            raise LifecycleTransitionError(str(exc)) from exc
        current_status = self._status(trusted_run.status, "run state")
        expected_status = self._status(expected_previous_state, "expected previous state")
        if current_status is not expected_status:
            raise LifecycleStateConflictError(
                "expected previous state "
                f"{expected_status.value!r} does not match run state "
                f"{current_status.value!r}"
            )

        authority = self._context.actor_resolver.resolve(actor)
        self._validate_authority(authority, normalized_event)
        self._derive(current_status, normalized_event)

        if (current_status, normalized_event) in self._FIX_ROUND_TRANSITIONS:
            max_fix_rounds = trusted_run.contract_version.contract.max_fix_rounds
            if trusted_run.fix_round >= max_fix_rounds:
                failure_fact = FailureFact(
                    kind=FailureFactKind.MAX_FIX_ROUNDS_EXCEEDED,
                    task_id=trusted_run.task_id,
                    run_id=trusted_run.run_id,
                    contract_version=trusted_run.contract_version.version,
                    fix_round=trusted_run.fix_round,
                    max_fix_rounds=max_fix_rounds,
                    reason="new fix round rejected at the contract limit",
                )
                self._context.run_registry.record_failure(
                    trusted_run,
                    failure_fact,
                    _lifecycle_token=_LIFECYCLE_MUTATION_TOKEN,
                )
                raise FixRoundLimitExceeded(failure_fact)

        audited_event = TaskEvent._from_lifecycle(
            event_id=normalized_event_id,
            event_name=normalized_event,
            run=trusted_run,
            registry=self._context.run_registry,
            actor_resolver=self._context.actor_resolver,
            actor=actor,
            expected_previous_state=expected_status,
        )
        self._context.run_registry.commit_transition(
            trusted_run,
            new_state=audited_event.new_state,
            fix_round=audited_event.fix_round,
            _lifecycle_token=_LIFECYCLE_MUTATION_TOKEN,
        )
        return audited_event

    def transition(
        self,
        run: Any,
        event: str,
        *,
        event_id: str,
        actor: ActorPrincipal,
        expected_previous_state: TaskStatus,
    ) -> TaskStatus:
        """Apply one trusted transition and return its derived next status."""

        return self.apply(
            run,
            event,
            event_id=event_id,
            actor=actor,
            expected_previous_state=expected_previous_state,
        ).new_state

    def update_contract(self, record: Any, contract_version: Any) -> Any:
        """Install a new contract and stale every active run for its task."""

        from .contracts import TaskRecord

        if not isinstance(record, TaskRecord):
            raise TypeError("record must be a TaskRecord")
        self._context.run_registry.require_record(record)
        updated_record = record.with_contract(contract_version)
        self._context.run_registry.stale_active_runs(
            record.task_id,
            _lifecycle_token=_LIFECYCLE_MUTATION_TOKEN,
        )
        return updated_record

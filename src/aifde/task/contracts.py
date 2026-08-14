"""Immutable task contracts, run snapshots and audited lifecycle events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .lifecycle import (
    ActorAuthority,
    ActorPrincipal,
    FailureFact,
    FailureFactKind,
    FixRoundLimitExceeded,
    LifecycleStateConflictError,
    LifecycleTransitionError,
    TaskRunRegistry,
    TaskStatus,
    TrustedActorResolver,
)


_TASK_EVENT_TOKEN = object()


def _normalize_nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value.strip()


def _normalize_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or value is None:
        raise ValueError(f"{field_name} must be a sequence of strings")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a sequence of strings") from exc
    return tuple(_normalize_nonblank(item, field_name) for item in items)


class TaskContract(BaseModel):
    """The immutable scope and governance contract for one task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    project_id: str
    domain_pack: str
    task_kind: str
    objective: str
    decision_owner: str
    required_outputs: tuple[str, ...] = Field(min_length=1)
    acceptance: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    risk_tier: str = "medium"
    human_checkpoints: tuple[str, ...] = ()
    max_fix_rounds: int = Field(default=3, ge=0)
    timeout_seconds: int = Field(default=3600, gt=0)

    @field_validator(
        "task_id",
        "project_id",
        "domain_pack",
        "task_kind",
        "objective",
        "decision_owner",
        "risk_tier",
    )
    @classmethod
    def require_nonblank(cls, value: str, info: Any) -> str:
        return _normalize_nonblank(value, info.field_name)

    @field_validator("required_outputs", "acceptance", "human_checkpoints", mode="before")
    @classmethod
    def normalize_sequences(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _normalize_sequence(value, info.field_name)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def normalize_evidence_refs(cls, value: Any) -> tuple[str, ...]:
        refs = _normalize_sequence(value, "evidence_refs")
        return tuple(dict.fromkeys(refs))


class TaskContractVersion(BaseModel):
    """An immutable numbered snapshot of a task contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: TaskContract
    version: int = Field(default=1, ge=1)
    created_at: datetime | None = None


_TERMINAL_RUN_STATES = frozenset(
    {TaskStatus.STALE, TaskStatus.RELEASED, TaskStatus.CANCELED}
)


class TaskRun(BaseModel):
    """An immutable run bound to one contract-version snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    contract_version: TaskContractVersion
    status: TaskStatus = TaskStatus.READY
    fix_round: int = Field(default=0, ge=0)
    failure_facts: tuple[FailureFact, ...] = ()

    @field_validator("run_id")
    @classmethod
    def require_run_id(cls, value: str) -> str:
        return _normalize_nonblank(value, "run_id")

    @property
    def task_id(self) -> str:
        return self.contract_version.contract.task_id

    @property
    def is_active(self) -> bool:
        return self.status not in _TERMINAL_RUN_STATES

    @model_validator(mode="after")
    def validate_fix_round_against_contract(self) -> "TaskRun":
        if self.fix_round > self.contract_version.contract.max_fix_rounds:
            raise ValueError(
                "fix_round cannot exceed contract max_fix_rounds"
            )
        return self


class TaskRecord(BaseModel):
    """An immutable task projection with its current version and run snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    contract_version: TaskContractVersion
    status: TaskStatus = TaskStatus.INTAKE
    runs: tuple[TaskRun, ...] = ()
    run_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_contract_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        values = dict(data)
        legacy_contract = values.pop("contract", None)
        raw_version = values.get("contract_version")

        if isinstance(raw_version, int) and not isinstance(raw_version, bool):
            if legacy_contract is None:
                raise ValueError(
                    "contract is required when contract_version is supplied as an integer"
                )
            values["contract_version"] = TaskContractVersion(
                contract=legacy_contract,
                version=raw_version,
            )
        elif legacy_contract is not None:
            if raw_version is None:
                values["contract_version"] = TaskContractVersion(contract=legacy_contract)
            elif isinstance(raw_version, TaskContractVersion):
                if raw_version.contract != legacy_contract:
                    raise ValueError(
                        "contract must match the contract-version snapshot"
                    )
            else:
                parsed_version = TaskContractVersion.model_validate(raw_version)
                if parsed_version.contract != legacy_contract:
                    raise ValueError(
                        "contract must match the contract-version snapshot"
                    )

        return values

    @field_validator("task_id")
    @classmethod
    def require_task_id(cls, value: str) -> str:
        return _normalize_nonblank(value, "task_id")

    @field_validator("run_id")
    @classmethod
    def normalize_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_nonblank(value, "run_id")

    @model_validator(mode="after")
    def validate_version_and_runs(self) -> "TaskRecord":
        if self.contract_version.contract.task_id != self.task_id:
            raise ValueError("task_id must match the contract-version snapshot")

        for run in self.runs:
            if run.task_id != self.task_id:
                raise ValueError("every run must belong to the task record")

        if self.run_id is not None:
            matching_runs = tuple(run for run in self.runs if run.run_id == self.run_id)
            if not matching_runs:
                raise ValueError("run_id must identify a run in the task record")

        return self

    @property
    def contract(self) -> TaskContract:
        """Compatibility view; the stored source of truth is the snapshot."""

        return self.contract_version.contract

    @property
    def contract_version_number(self) -> int:
        return self.contract_version.version

    def with_contract(self, contract_version: TaskContractVersion) -> "TaskRecord":
        """Return a new record and stale every non-terminal run."""

        if not isinstance(contract_version, TaskContractVersion):
            raise TypeError("contract_version must be a TaskContractVersion")
        if contract_version.contract.task_id != self.task_id:
            raise ValueError("new contract must belong to the task record")
        if contract_version.version <= self.contract_version.version:
            raise ValueError("new contract version must be greater than the current version")

        updated_runs = tuple(
            run.model_copy(update={"status": TaskStatus.STALE})
            if run.is_active
            else run
            for run in self.runs
        )
        return self.model_copy(
            update={
                "contract_version": contract_version,
                "status": TaskStatus.READY,
                "runs": updated_runs,
                "run_id": None,
            }
        )


class TaskEvent(BaseModel):
    """An immutable event issued only by the trusted lifecycle factory.

    A caller-supplied ``authority`` is not an authentication mechanism.  The
    normal constructor therefore rejects all inputs; ``TaskLifecycle`` uses
    the private factory below after resolving a principal against its bound
    resolver.  Persistence adapters should accept only events produced this
    way (and re-check the actor binding if they deserialize untrusted data).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    task_id: str
    event_name: str
    actor: str
    authority: ActorAuthority
    previous_state: TaskStatus
    expected_previous_state: TaskStatus
    run_id: str
    contract_version: int = Field(ge=1)
    fix_round: int = Field(ge=0)

    def __init__(self, **data: Any) -> None:
        token = data.pop("_lifecycle_token", None)
        if token is not _TASK_EVENT_TOKEN:
            raise TypeError("TaskEvent can only be created by the trusted lifecycle")
        super().__init__(**data)

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: Any,
    ) -> "TaskEvent":
        token = values.pop("_lifecycle_token", None)
        if token is not _TASK_EVENT_TOKEN:
            raise TypeError("TaskEvent can only be constructed by the trusted lifecycle")
        return super().model_construct(_fields_set=_fields_set, **values)

    def model_copy(
        self,
        *,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> "TaskEvent":
        if update:
            raise TypeError("TaskEvent copies cannot be modified outside the lifecycle")
        return super().model_copy(deep=deep)

    @classmethod
    def _from_lifecycle(
        cls,
        *,
        event_id: str,
        event_name: str,
        run: Any,
        registry: TaskRunRegistry,
        actor_resolver: TrustedActorResolver,
        actor: ActorPrincipal,
        expected_previous_state: TaskStatus,
    ) -> "TaskEvent":
        """Create an event from trusted lifecycle dependencies only.

        Audit identity, authority, contract metadata and fix round are all
        derived here.  The factory intentionally has no parameters for those
        fields, so a caller cannot turn a self-reported authority mapping or a
        copied run into an approval event.
        """

        from .lifecycle import TaskLifecycle

        if not isinstance(registry, TaskRunRegistry):
            raise TypeError("event factory requires a TaskRunRegistry")
        if not isinstance(actor_resolver, TrustedActorResolver):
            raise TypeError("event factory requires a TrustedActorResolver")

        trusted_run = registry.require_registered(run)
        if not trusted_run.is_active:
            raise LifecycleTransitionError(
                f"stale or inactive run cannot issue events: {trusted_run.run_id!r}"
            )

        try:
            normalized_event_id = _normalize_nonblank(event_id, "event_id")
            normalized_event = _normalize_nonblank(event_name, "event")
        except ValueError as exc:
            raise LifecycleTransitionError(str(exc)) from exc

        current_status = TaskLifecycle._status(trusted_run.status, "run state")
        expected_status = TaskLifecycle._status(
            expected_previous_state,
            "expected previous state",
        )
        if current_status is not expected_status:
            raise LifecycleStateConflictError(
                "expected previous state "
                f"{expected_status.value!r} does not match run state "
                f"{current_status.value!r}"
            )

        authority = actor_resolver.resolve(actor)
        TaskLifecycle._validate_authority(authority, normalized_event)
        TaskLifecycle._derive(current_status, normalized_event)

        next_fix_round = trusted_run.fix_round
        if (current_status, normalized_event) in TaskLifecycle._FIX_ROUND_TRANSITIONS:
            max_fix_rounds = trusted_run.contract_version.contract.max_fix_rounds
            if trusted_run.fix_round >= max_fix_rounds:
                raise FixRoundLimitExceeded(
                    FailureFact(
                        kind=FailureFactKind.MAX_FIX_ROUNDS_EXCEEDED,
                        task_id=trusted_run.task_id,
                        run_id=trusted_run.run_id,
                        contract_version=trusted_run.contract_version.version,
                        fix_round=trusted_run.fix_round,
                        max_fix_rounds=max_fix_rounds,
                        reason="new fix round rejected at the contract limit",
                    )
                )
            next_fix_round += 1

        return cls(
            _lifecycle_token=_TASK_EVENT_TOKEN,
            event_id=normalized_event_id,
            task_id=trusted_run.task_id,
            event_name=normalized_event,
            actor=actor.actor_id,
            authority=authority,
            previous_state=current_status,
            expected_previous_state=expected_status,
            run_id=trusted_run.run_id,
            contract_version=trusted_run.contract_version.version,
            fix_round=next_fix_round,
        )

    @field_validator("event_id", "task_id", "event_name", "actor", "run_id")
    @classmethod
    def require_nonblank(cls, value: str, info: Any) -> str:
        return _normalize_nonblank(value, info.field_name)

    @model_validator(mode="after")
    def validate_event(self) -> "TaskEvent":
        if self.previous_state is not self.expected_previous_state:
            raise ValueError("previous_state must match expected_previous_state")

        from .lifecycle import TaskLifecycle

        TaskLifecycle._validate_authority(self.authority, self.event_name)
        TaskLifecycle._derive(self.previous_state, self.event_name)
        return self

    @computed_field(return_type=TaskStatus)
    @property
    def new_state(self) -> TaskStatus:
        from .lifecycle import TaskLifecycle

        return TaskLifecycle._derive(self.previous_state, self.event_name)

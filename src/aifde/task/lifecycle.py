"""Pure task lifecycle state transitions."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar


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


class LifecycleTransitionError(ValueError):
    """Raised when a lifecycle event is unknown or not legal for a state."""


class TaskLifecycle:
    """Deterministic state machine for governed tasks."""

    _TRANSITIONS: ClassVar[dict[tuple[TaskStatus, str], TaskStatus]] = {
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

    @staticmethod
    def transition(current: TaskStatus, event: str) -> TaskStatus:
        """Return the next state for ``event`` without mutating any state."""

        try:
            current_status = TaskStatus(current)
        except (TypeError, ValueError) as exc:
            raise LifecycleTransitionError(f"unknown current task status: {current!r}") from exc

        if not isinstance(event, str):
            raise LifecycleTransitionError(f"unknown lifecycle event: {event!r}")

        try:
            return TaskLifecycle._TRANSITIONS[(current_status, event)]
        except KeyError as exc:
            raise LifecycleTransitionError(
                f"illegal lifecycle transition from {current_status.value!r} using {event!r}"
            ) from exc

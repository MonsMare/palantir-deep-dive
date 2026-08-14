"""Domain-independent governed task contracts and lifecycle kernel."""

from .contracts import (
    TaskContract,
    TaskContractVersion,
    TaskEvent,
    TaskRecord,
    TaskRun,
)
from .lifecycle import (
    ActorAuthority,
    AuthorityPolicy,
    FailureFact,
    FailureFactKind,
    FixRoundLimitExceeded,
    LifecycleStateConflictError,
    LifecycleTransitionError,
    TaskLifecycle,
    TaskStatus,
    UnauthorizedActorError,
)

__all__ = [
    "LifecycleTransitionError",
    "LifecycleStateConflictError",
    "UnauthorizedActorError",
    "ActorAuthority",
    "AuthorityPolicy",
    "FailureFact",
    "FailureFactKind",
    "FixRoundLimitExceeded",
    "TaskContract",
    "TaskContractVersion",
    "TaskEvent",
    "TaskLifecycle",
    "TaskRecord",
    "TaskRun",
    "TaskStatus",
]

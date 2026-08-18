"""Domain-independent governed task contracts and lifecycle kernel."""

from .contracts import (
    TaskContract,
    TaskContractVersion,
    TaskEvent,
    TaskRecord,
    TaskRun,
)
from .lifecycle import (
    ActorPrincipal,
    ActorAuthority,
    AuthorityPolicy,
    FailureFact,
    FailureFactKind,
    FixRoundLimitExceeded,
    LifecycleStateConflictError,
    LifecycleTransitionError,
    TaskLifecycle,
    TaskLifecycleContext,
    TaskRunRegistry,
    TaskStatus,
    TrustedActorResolver,
    TrustedPrincipal,
    UnauthorizedActorError,
)

__all__ = [
    "LifecycleTransitionError",
    "LifecycleStateConflictError",
    "UnauthorizedActorError",
    "ActorAuthority",
    "ActorPrincipal",
    "AuthorityPolicy",
    "FailureFact",
    "FailureFactKind",
    "FixRoundLimitExceeded",
    "TaskContract",
    "TaskContractVersion",
    "TaskEvent",
    "TaskLifecycle",
    "TaskLifecycleContext",
    "TaskRecord",
    "TaskRunRegistry",
    "TaskRun",
    "TaskStatus",
    "TrustedActorResolver",
    "TrustedPrincipal",
]

"""Gate result domain contract."""

from enum import Enum


class GateResult(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    PENDING = "pending"

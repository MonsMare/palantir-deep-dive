"""Bounded execution budgets for domain-agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BudgetExhausted(RuntimeError):
    """Raised before an agent starts when the run cannot stay within budget."""


class BudgetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tokens: int = 50_000
    max_wall_seconds: float = 3_600.0
    max_nodes: int = 100
    max_retries: int = 3

    @field_validator("max_tokens", "max_nodes")
    @classmethod
    def require_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("budget integer limits must be positive")
        return value

    @field_validator("max_wall_seconds")
    @classmethod
    def require_positive_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("max_wall_seconds must be positive")
        return value

    @field_validator("max_retries")
    @classmethod
    def require_nonnegative_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_retries must be non-negative")
        return value


class BudgetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    used_tokens: int
    used_nodes: int
    used_retries: int
    elapsed_seconds: float
    exhausted: bool
    reason: str | None = None


@dataclass
class _Reservation:
    token_budget: int
    retry: bool


class BudgetLedger:
    """Thread-safe reservation ledger; rejection happens before execution."""

    def __init__(self, spec: BudgetSpec | None = None) -> None:
        self.spec = spec or BudgetSpec()
        self._started_at = monotonic()
        self._used_tokens = 0
        self._used_nodes = 0
        self._used_retries = 0
        self._reserved_tokens = 0
        self._active: dict[str, _Reservation] = {}
        self._reason: str | None = None
        self._lock = RLock()

    def reserve(self, node_id: str, *, token_budget: int, retry: bool = False) -> BudgetSnapshot:
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("node_id must not be blank")
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        with self._lock:
            self._check_wall()
            if node_id in self._active:
                raise RuntimeError(f"node already has an active reservation: {node_id}")
            if self._used_nodes + len(self._active) >= self.spec.max_nodes:
                raise BudgetExhausted("max_nodes budget exhausted")
            if self._used_tokens + self._reserved_tokens + token_budget > self.spec.max_tokens:
                raise BudgetExhausted("max_tokens budget exhausted")
            if retry and self._used_retries + 1 > self.spec.max_retries:
                raise BudgetExhausted("max_retries budget exhausted")
            self._active[node_id] = _Reservation(token_budget=token_budget, retry=retry)
            self._reserved_tokens += token_budget
            return self.snapshot()

    def complete(self, node_id: str, *, token_usage: int) -> BudgetSnapshot:
        if token_usage < 0:
            raise ValueError("token_usage must be non-negative")
        with self._lock:
            reservation = self._active.pop(node_id, None)
            if reservation is None:
                raise KeyError(f"no active budget reservation: {node_id}")
            self._reserved_tokens -= reservation.token_budget
            self._used_tokens += token_usage
            self._used_nodes += 1
            if reservation.retry:
                self._used_retries += 1
            if self._used_tokens > self.spec.max_tokens:
                self._reason = "actual token usage exceeded max_tokens"
                raise BudgetExhausted(self._reason)
            return self.snapshot()

    def cancel(self, node_id: str) -> BudgetSnapshot:
        with self._lock:
            reservation = self._active.pop(node_id, None)
            if reservation is not None:
                self._reserved_tokens -= reservation.token_budget
            return self.snapshot()

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            elapsed = monotonic() - self._started_at
            exhausted = self._reason is not None
            return BudgetSnapshot(
                used_tokens=self._used_tokens,
                used_nodes=self._used_nodes,
                used_retries=self._used_retries,
                elapsed_seconds=elapsed,
                exhausted=exhausted,
                reason=self._reason,
            )

    def _check_wall(self) -> None:
        if monotonic() - self._started_at >= self.spec.max_wall_seconds:
            self._reason = "max_wall_seconds budget exhausted"
            raise BudgetExhausted(self._reason)


__all__ = ["BudgetExhausted", "BudgetLedger", "BudgetSnapshot", "BudgetSpec"]

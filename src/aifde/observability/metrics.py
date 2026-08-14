"""Small dependency-free metrics registry for the local and hosted runtimes."""

from __future__ import annotations

from threading import RLock
from typing import Mapping


class MetricsRegistry:
    """Thread-safe counters and last-value gauges with deterministic keys."""

    def __init__(self) -> None:
        self._values: dict[str, float] = {}
        self._lock = RLock()

    def increment(
        self,
        name: str,
        *,
        amount: int | float = 1,
        labels: Mapping[str, str] | None = None,
    ) -> float:
        key = _metric_key(name, labels)
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise TypeError("metric amount must be numeric")
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + float(amount)
            return self._values[key]

    def observe(
        self,
        name: str,
        value: int | float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> float:
        key = _metric_key(name, labels)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("metric value must be numeric")
        with self._lock:
            self._values[key] = float(value)
            return self._values[key]

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)


def _metric_key(name: str, labels: Mapping[str, str] | None) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("metric name must not be blank")
    normalized = dict(labels or {})
    for key, value in normalized.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip():
            raise ValueError("metric labels must contain non-empty strings")
    suffix = "|" + ",".join(f"{key}={normalized[key]}" for key in sorted(normalized))
    return name.strip() + suffix


__all__ = ["MetricsRegistry"]

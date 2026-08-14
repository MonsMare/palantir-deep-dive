"""Fail-closed liveness/readiness primitives for platform dependencies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str
    status: Literal["ready", "not_ready"]
    detail: str


class ReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool
    checks: dict[str, HealthCheck]


class ReadinessChecker:
    """Evaluate persistence, registry, connector, queue, and policy probes."""

    def __init__(self, checks: Mapping[str, Callable[[], bool | HealthCheck]]) -> None:
        if not checks:
            raise ValueError("at least one readiness check is required")
        self._checks = dict(checks)

    def check(self) -> ReadinessReport:
        results: dict[str, HealthCheck] = {}
        for component, probe in self._checks.items():
            if not isinstance(component, str) or not component.strip():
                raise ValueError("readiness component must not be blank")
            try:
                outcome = probe()
                if isinstance(outcome, HealthCheck):
                    result = outcome
                else:
                    result = HealthCheck(
                        component=component,
                        status="ready" if outcome else "not_ready",
                        detail="probe passed" if outcome else "probe returned false",
                    )
            except Exception as exc:  # fail closed at the boundary
                result = HealthCheck(
                    component=component,
                    status="not_ready",
                    detail=f"probe failed: {exc}",
                )
            results[component] = result
        return ReadinessReport(
            ready=all(item.status == "ready" for item in results.values()),
            checks=results,
        )


__all__ = ["HealthCheck", "ReadinessChecker", "ReadinessReport"]

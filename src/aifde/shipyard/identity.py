"""Trusted identity bindings for the Shipyard application boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol


PrincipalKind = Literal["human", "agent", "system"]
_PRINCIPAL_KINDS = frozenset({"human", "agent", "system"})


class UnauthorizedError(PermissionError):
    """The caller is not authorized for the requested application operation."""


@dataclass(frozen=True, slots=True)
class Principal:
    """An identity resolved by a trusted boundary, not by request JSON."""

    subject: str
    kind: PrincipalKind
    roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("subject must not be blank")
        if self.kind not in _PRINCIPAL_KINDS:
            raise ValueError("kind must be human, agent, or system")
        if isinstance(self.roles, str):
            raise TypeError("roles must be a collection of strings")
        try:
            normalized_roles = frozenset(self.roles)
        except TypeError as exc:
            raise TypeError("roles must be a collection of strings") from exc
        if any(not isinstance(role, str) or not role.strip() for role in normalized_roles):
            raise ValueError("roles must contain non-blank strings")
        object.__setattr__(self, "subject", self.subject.strip())
        object.__setattr__(
            self,
            "roles",
            frozenset(role.strip() for role in normalized_roles),
        )


class IdentityProvider(Protocol):
    """Resolve an authenticated request context to an explicit Principal."""

    def resolve(self, request_context: Mapping[str, str]) -> Principal:
        """Return the preconfigured identity represented by the request context."""

    def verify(self, principal: Principal) -> Principal:
        """Return the canonical bound Principal or reject the supplied claim."""


class FakeIdentityProvider:
    """Explicit in-memory identity directory for local and test use only."""

    def __init__(self) -> None:
        self._bindings: dict[str, Principal] = {}

    def bind(
        self,
        subject: str,
        kind: PrincipalKind,
        roles: Iterable[str] = (),
    ) -> Principal:
        """Create or replace one explicit local binding.

        No authority is inferred from the subject string.  In particular,
        names such as ``agent-1`` have no meaning until explicitly bound.
        """

        principal = Principal(subject=subject, kind=kind, roles=frozenset(roles))
        self._bindings[principal.subject] = principal
        return principal

    def resolve(self, request_context: Mapping[str, str]) -> Principal:
        if not isinstance(request_context, Mapping):
            raise UnauthorizedError("request context is not a mapping")

        subject: object | None = None
        for key in (
            "subject",
            "X-Shipyard-Identity",
            "x-shipyard-identity",
        ):
            if key in request_context:
                subject = request_context[key]
                break
        if not isinstance(subject, str) or not subject.strip():
            raise UnauthorizedError("request context does not contain an identity")

        principal = self._bindings.get(subject.strip())
        if principal is None:
            raise UnauthorizedError(f"unknown identity: {subject.strip()}")
        return principal

    def verify(self, principal: Principal) -> Principal:
        """Verify an application caller against an exact explicit binding."""

        if not isinstance(principal, Principal):
            raise UnauthorizedError("operation requires a Principal")
        bound = self._bindings.get(principal.subject)
        if bound is None:
            raise UnauthorizedError(f"unknown identity: {principal.subject}")
        if bound != principal:
            raise UnauthorizedError(
                f"identity claim does not match the binding for {principal.subject}"
            )
        return bound


__all__ = [
    "FakeIdentityProvider",
    "IdentityProvider",
    "Principal",
    "PrincipalKind",
    "UnauthorizedError",
]

"""Typed protocols shared by tools and the Tool Gateway."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from math import isfinite
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.policy.capabilities import Capability, ToolContext


class _ImmutableList(list[Any]):
    """List-shaped defensive value whose every mutation fails closed."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable tool result")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable


class _ImmutableDict(dict[str, Any]):
    """Dict-shaped recursive defensive value whose every mutation fails closed."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable tool result")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable


def _json_immutable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("payload floats must be finite")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("payload mapping keys must be strings")
        return _ImmutableDict(
            {key: _json_immutable(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return _ImmutableList(_json_immutable(item) for item in value)
    raise TypeError("payload must contain JSON-compatible values")


class ToolResult(BaseModel):
    """The only result shape a tool may return through the gateway.

    The public shape remains list/dict-like for compatibility, but all nested
    values are defensive immutable containers.  This prevents a caller from
    changing a returned result after the gateway has audited it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    status: str
    artifact_ids: Any = Field(default_factory=_ImmutableList)
    evidence_refs: Any = Field(default_factory=_ImmutableList)
    payload: Any = Field(default_factory=_ImmutableDict)
    audit_id: str = Field(default_factory=lambda: str(uuid4()))

    @field_validator("status", "audit_id")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()

    @field_validator("artifact_ids", "evidence_refs", mode="before")
    @classmethod
    def normalize_references(cls, value: Any) -> _ImmutableList:
        if isinstance(value, (str, bytes)):
            raise TypeError("references must be an iterable of non-empty strings")
        try:
            values = list(value)
        except TypeError as exc:
            raise TypeError("references must be an iterable of non-empty strings") from exc
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError("references must contain non-empty strings")
        if any(item != item.strip() for item in values):
            raise ValueError("references must use canonical identities")
        return _ImmutableList(values)

    @field_validator("payload", mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> _ImmutableDict:
        if not isinstance(value, Mapping):
            raise TypeError("payload must be a mapping")
        return _json_immutable(value)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Revalidate copies so ``model_copy`` cannot reintroduce mutability."""

        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)


@runtime_checkable
class Tool(Protocol):
    """A tool receives only context/payload and returns a typed result."""

    tool_id: str
    required_capabilities: frozenset[Capability]
    allowed_stage_ids: frozenset[str]

    def call(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        """Perform a bounded operation; Gateway registration guards this method."""
        ...


__all__ = ["Capability", "Tool", "ToolContext", "ToolResult"]

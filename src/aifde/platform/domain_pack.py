"""Versioned domain-pack contracts and registry."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ontology_ir import OntologyIR


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a mapping")
    return deepcopy(value)


def _mapping_tuple(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{name} must be a sequence of mappings")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{name} must contain mappings")
        result.append(deepcopy(item))
    return tuple(result)


class DomainPack(BaseModel):
    """A complete domain definition consumed by the platform runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: str
    version: str
    domain: str
    vocabulary: dict[str, str]
    ontology: OntologyIR
    mappings: tuple[dict[str, Any], ...] = ()
    computation: dict[str, Any] = Field(default_factory=dict)
    decisions: dict[str, Any] = Field(default_factory=dict)
    actions: dict[str, Any] = Field(default_factory=dict)
    acceptance_suite: dict[str, Any] = Field(default_factory=dict)

    @field_validator("pack_id", "version", "domain")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @field_validator("vocabulary", "computation", "decisions", "actions", "acceptance_suite", mode="before")
    @classmethod
    def normalize_mapping(cls, value: Any, info: Any) -> dict[str, Any]:
        return _mapping(value, info.field_name)

    @field_validator("mappings", mode="before")
    @classmethod
    def normalize_mappings(cls, value: Any) -> tuple[dict[str, Any], ...]:
        return _mapping_tuple(value, "mappings")


class DomainPackRegistry:
    """Thread-safe append-only registry keyed by pack id and version."""

    def __init__(self, packs: Iterable[DomainPack] = ()) -> None:
        self._packs: dict[tuple[str, str], DomainPack] = {}
        self._lock = RLock()
        for pack in packs:
            self.register(pack)

    def register(self, pack: DomainPack) -> DomainPack:
        if not isinstance(pack, DomainPack):
            raise TypeError("pack must be a DomainPack")
        key = (pack.pack_id, pack.version)
        with self._lock:
            existing = self._packs.get(key)
            if existing is not None:
                if existing != pack:
                    raise ValueError(f"domain pack {pack.pack_id}@{pack.version} is immutable")
                return existing.model_copy(deep=True)
            self._packs[key] = pack.model_copy(deep=True)
            return pack.model_copy(deep=True)

    def get(self, pack_id: str, version: str | None = None) -> DomainPack:
        pack_id = _text(pack_id, "pack_id")
        with self._lock:
            if version is not None:
                key = (pack_id, _text(version, "version"))
                try:
                    return self._packs[key].model_copy(deep=True)
                except KeyError as exc:
                    raise KeyError(f"{pack_id}@{key[1]}") from exc
            candidates = [pack for (candidate_id, _), pack in self._packs.items() if candidate_id == pack_id]
            if not candidates:
                raise KeyError(pack_id)
            selected = max(candidates, key=lambda item: _version_key(item.version))
            return selected.model_copy(deep=True)

    def list(self) -> list[DomainPack]:
        with self._lock:
            return [
                self._packs[key].model_copy(deep=True)
                for key in sorted(self._packs, key=lambda item: (item[0], _version_key(item[1])))
            ]


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


__all__ = ["DomainPack", "DomainPackRegistry"]

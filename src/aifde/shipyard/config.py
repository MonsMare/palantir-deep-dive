"""Strict configuration and filesystem layout for the Local Shipyard profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _is_within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


@dataclass(frozen=True, slots=True)
class ShipyardPaths:
    """The state directories owned by one local Shipyard project."""

    project_root: Path
    state_root: Path
    database_path: Path
    artifact_path: Path
    evidence_path: Path
    workspaces_path: Path
    runs_path: Path
    logs_path: Path
    releases_path: Path
    plugins_path: Path
    cache_path: Path
    secrets_path: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> ShipyardPaths:
        root = project_root.expanduser().resolve()
        state = root / ".shipyard"
        return cls(
            project_root=root,
            state_root=state,
            database_path=state / "shipyard.db",
            artifact_path=state / "artifacts",
            evidence_path=state / "evidence",
            workspaces_path=state / "workspaces",
            runs_path=state / "runs",
            logs_path=state / "logs",
            releases_path=state / "releases",
            plugins_path=state / "plugins",
            cache_path=state / "cache",
            secrets_path=state / "secrets",
        )

    def ensure_directories(self) -> None:
        """Create local state directories without replacing existing files."""

        for path in (
            self.state_root,
            self.artifact_path,
            self.evidence_path,
            self.workspaces_path,
            self.runs_path,
            self.logs_path,
            self.releases_path,
            self.plugins_path,
            self.cache_path,
            self.secrets_path,
        ):
            path.mkdir(parents=True, exist_ok=True)


class LocalServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=3080, ge=1024, le=65535)
    open_browser: bool = False


class LocalSandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filesystem: Literal["workspace_only"] = "workspace_only"
    network: Literal["deny"] = "deny"
    production_actions: Literal["deny"] = "deny"


class LocalRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    profile: Literal["local"] = "local"
    project_root: Path
    owner: str
    frontend_dir: str = "workbench/dist"
    required_gate_ids: tuple[str, ...] = (
        "semantic.integrity",
        "release.governance",
    )
    server: LocalServerConfig = Field(default_factory=LocalServerConfig)
    sandbox: LocalSandboxConfig = Field(default_factory=LocalSandboxConfig)

    @property
    def paths(self) -> ShipyardPaths:
        return ShipyardPaths.from_project_root(self.project_root)

    def resolve_frontend_dir(self) -> Path:
        candidate = Path(self.frontend_dir)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        resolved = candidate.expanduser().resolve()
        if not _is_within(resolved, self.project_root.resolve()):
            raise ValueError("frontend_dir must remain inside project_root")
        return resolved

    @field_validator("owner")
    @classmethod
    def require_owner(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("owner must not be blank")
        return value.strip()

    @field_validator("required_gate_ids")
    @classmethod
    def require_gate_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if not normalized or any(not item for item in normalized):
            raise ValueError("required_gate_ids must contain non-blank values")
        return tuple(dict.fromkeys(normalized))

    @classmethod
    def load(
        cls,
        project_root: Path,
        config_path: Path | None = None,
    ) -> LocalRuntimeConfig:
        root = project_root.expanduser().resolve()
        path = config_path or (root / ".shipyard/config.yaml")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("local runtime config must be a mapping")
        values: dict[str, Any] = dict(raw)
        values["project_root"] = root
        config = cls.model_validate(values)
        config.resolve_frontend_dir()
        return config


def write_default_config(
    project_root: Path,
    *,
    owner: str,
    force: bool = False,
) -> Path:
    root = project_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("project_root must be an existing directory")

    path = root / ".shipyard/config.yaml"
    if path.exists() and not force:
        raise FileExistsError(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(
            {
                "schema_version": 1,
                "profile": "local",
                "owner": owner,
                "frontend_dir": "workbench/dist",
                "required_gate_ids": [
                    "semantic.integrity",
                    "release.governance",
                ],
                "server": {
                    "host": "127.0.0.1",
                    "port": 3080,
                    "open_browser": False,
                },
                "sandbox": {
                    "filesystem": "workspace_only",
                    "network": "deny",
                    "production_actions": "deny",
                },
            },
            stream,
            sort_keys=False,
            allow_unicode=True,
        )
    return path

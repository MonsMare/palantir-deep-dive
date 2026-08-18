from pathlib import Path

import pytest

from aifde.shipyard.config import (
    LocalRuntimeConfig,
    ShipyardPaths,
    write_default_config,
)


def test_default_config_creates_local_profile_and_project_state(tmp_path: Path) -> None:
    config_path = write_default_config(tmp_path, owner="alice")

    config = LocalRuntimeConfig.load(tmp_path, config_path)

    assert config.profile == "local"
    assert config.owner == "alice"
    assert config.server.host == "127.0.0.1"
    assert config.server.port == 3080
    assert config.required_gate_ids == (
        "semantic.integrity",
        "release.governance",
    )
    assert config.paths.database_path == (tmp_path / ".shipyard/shipyard.db").resolve()
    assert config.resolve_frontend_dir() == (tmp_path / "workbench/dist").resolve()


def test_paths_are_created_without_deleting_existing_state(tmp_path: Path) -> None:
    paths = ShipyardPaths.from_project_root(tmp_path)
    paths.artifact_path.mkdir(parents=True)
    marker = paths.artifact_path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    paths.ensure_directories()

    assert marker.read_text(encoding="utf-8") == "keep"
    assert paths.database_path.parent.is_dir()
    assert paths.evidence_path.is_dir()
    assert paths.runs_path.is_dir()
    assert paths.logs_path.is_dir()
    assert paths.releases_path.is_dir()
    assert paths.plugins_path.is_dir()


def test_config_rejects_non_loopback_host(tmp_path: Path) -> None:
    config_path = write_default_config(tmp_path, owner="alice")
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace("host: 127.0.0.1", "host: 0.0.0.0"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="127.0.0.1"):
        LocalRuntimeConfig.load(tmp_path, config_path)


def test_config_rejects_frontend_path_escape(tmp_path: Path) -> None:
    config_path = write_default_config(tmp_path, owner="alice")
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace("frontend_dir: workbench/dist", "frontend_dir: ../outside"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inside project_root"):
        LocalRuntimeConfig.load(tmp_path, config_path)


def test_default_config_refuses_overwrite_without_force(tmp_path: Path) -> None:
    write_default_config(tmp_path, owner="alice")

    with pytest.raises(FileExistsError):
        write_default_config(tmp_path, owner="bob")

from pathlib import Path

from aifde.shipyard import cli


def test_init_creates_config_and_runtime_directories(tmp_path: Path) -> None:
    exit_code = cli.main(["init", str(tmp_path), "--owner", "alice"])

    assert exit_code == 0
    assert (tmp_path / ".shipyard/config.yaml").is_file()
    assert (tmp_path / ".shipyard/artifacts").is_dir()
    assert (tmp_path / ".shipyard/shipyard.db").exists() is False


def test_init_does_not_overwrite_without_force(tmp_path: Path) -> None:
    assert cli.main(["init", str(tmp_path), "--owner", "alice"]) == 0

    assert cli.main(["init", str(tmp_path), "--owner", "bob"]) == 2


def test_web_delegates_to_injected_local_web_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cli.main(["init", str(tmp_path), "--owner", "alice"])
    frontend = tmp_path / "workbench/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("workbench", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(runtime, *, uvicorn_runner=None, browser_opener=None):
        captured.update(
            runtime=runtime,
            host=runtime.config.server.host,
            port=runtime.config.server.port,
        )

    monkeypatch.setattr(cli, "run_local_web", fake_run)

    assert cli.main(["web", "--project", str(tmp_path)]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 3080

"""Command-line entry points for the Local Shipyard Web Runtime."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import sys
import webbrowser
from typing import Any

from .config import LocalRuntimeConfig, write_default_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shipyard",
        description="Build and review AI-FDE Shipyard decision-system releases",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="initialize a local Shipyard project state directory",
    )
    init_parser.add_argument(
        "project_directory",
        type=Path,
        help="existing project directory",
    )
    init_parser.add_argument(
        "--owner",
        required=True,
        help="local human owner subject",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="replace config.yaml without deleting other local state",
    )

    web_parser = subparsers.add_parser(
        "web",
        help="serve the local Shipyard Workbench",
    )
    web_parser.add_argument(
        "--project",
        required=True,
        type=Path,
        help="project directory containing .shipyard/config.yaml",
    )
    web_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="optional Local Profile YAML path",
    )
    web_parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=None,
        help="optional Workbench dist directory inside the project",
    )
    web_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="override the configured local port",
    )
    web_parser.add_argument(
        "--open-browser",
        action="store_true",
        default=None,
        help="open the local URL after creating the runtime",
    )
    return parser


def _init_project(args: argparse.Namespace) -> int:
    root = args.project_directory.expanduser().resolve()
    config_path = write_default_config(
        root,
        owner=args.owner,
        force=args.force,
    )
    config = LocalRuntimeConfig.load(root, config_path)
    config.paths.ensure_directories()
    print(f"Initialized Shipyard Local Profile at {root}")
    print(f"Configuration: {config_path}")
    print(f"Start: shipyard web --project {root}")
    return 0


def run_local_web(
    runtime: Any,
    *,
    uvicorn_runner: Callable[..., Any] | None = None,
    browser_opener: Callable[[str], Any] | None = None,
) -> None:
    """Run one runtime and optionally open its browser URL."""

    if uvicorn_runner is None:
        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError(
                'Uvicorn is required for "shipyard web"; '
                'install it with python -m pip install -e ".[web]"'
            ) from exc
        uvicorn_runner = uvicorn.run

    if runtime.config.server.open_browser:
        (browser_opener or webbrowser.open)(runtime.url)

    uvicorn_runner(
        runtime.app,
        host=runtime.config.server.host,
        port=runtime.config.server.port,
        log_level="info",
    )


def _web_project(args: argparse.Namespace) -> int:
    from .runtime import build_local_runtime

    root = args.project.expanduser().resolve()
    config = LocalRuntimeConfig.load(root, args.config)
    updates: dict[str, Any] = {}
    if args.frontend_dir is not None:
        updates["frontend_dir"] = str(args.frontend_dir)

    server_updates: dict[str, Any] = {}
    if args.port is not None:
        server_updates["port"] = args.port
    if args.open_browser is not None:
        server_updates["open_browser"] = args.open_browser
    if server_updates:
        updates["server"] = config.server.model_copy(update=server_updates)
    if updates:
        config = config.model_copy(update=updates)
        config.resolve_frontend_dir()

    runtime = build_local_runtime(config)
    print(f"Shipyard Workbench: {runtime.url}")
    try:
        run_local_web(runtime)
    finally:
        runtime.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init_project(args)
        if args.command == "web":
            return _web_project(args)
        raise ValueError(f"unsupported command: {args.command}")
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"shipyard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

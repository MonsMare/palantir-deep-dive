"""Static Workbench asset resolution and mounting."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class FrontendNotBuiltError(RuntimeError):
    """Raised when the browser bundle is not available for local serving."""


def _is_within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


def resolve_workbench_dist(
    project_root: Path,
    configured_dir: Path | None = None,
) -> Path:
    root = project_root.expanduser().resolve()
    directory = configured_dir or (root / "workbench/dist")
    resolved = directory.expanduser().resolve()
    if not _is_within(resolved, root):
        raise ValueError("frontend directory must remain inside project_root")
    if not resolved.is_dir() or not (resolved / "index.html").is_file():
        raise FrontendNotBuiltError(
            "Workbench assets are missing; run npm run build before shipyard web"
        )
    return resolved


def mount_workbench(app: Any, directory: Path) -> None:
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/",
        StaticFiles(directory=directory, html=True),
        name="workbench",
    )

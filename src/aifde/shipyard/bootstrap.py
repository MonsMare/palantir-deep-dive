"""Deterministic bootstrap adapters for the software-delivery Shipyard slice.

This module is deliberately a builder-side adapter.  It reads the checked-in
software-delivery assets, turns them into immutable ``Artifact`` records and
asks the Shipyard application service to persist them.  It does not call a
customer connector or execute a production Action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

from aifde.domain.artifacts import Artifact
from aifde.shipyard.contracts import GateReviewSnapshot, ProjectWorkspace
from aifde.shipyard.evaluator import build_software_delivery_gate_reviews
from aifde.shipyard.identity import Principal, UnauthorizedError
from aifde.shipyard.provenance import (
    SOFTWARE_DELIVERY_ARTIFACT_ORDER,
    SOFTWARE_DELIVERY_ARTIFACT_IDS,
    SOFTWARE_DELIVERY_ARTIFACT_SPECS,
)
from aifde.shipyard.service import RecordNotFoundError

if TYPE_CHECKING:
    from aifde.shipyard.service import ShipyardApplicationService


PROJECT_ID = "software-delivery-demo"
WORKSPACE_ID = "workspace:software-delivery-demo"
SEED_PRODUCER = "shipyard-seed"
SEED_VERSION = "software-delivery-seed-v1"
SEED_CREATED_AT = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class _AssetSpec:
    key: str
    relative_path: str
    kind: str
    format: str


_ASSET_SPECS: tuple[_AssetSpec, ...] = tuple(
    _AssetSpec(
        SOFTWARE_DELIVERY_ARTIFACT_SPECS[artifact_id].key,
        SOFTWARE_DELIVERY_ARTIFACT_SPECS[artifact_id].relative_path,
        SOFTWARE_DELIVERY_ARTIFACT_SPECS[artifact_id].kind,
        SOFTWARE_DELIVERY_ARTIFACT_SPECS[artifact_id].format,
    )
    for artifact_id in SOFTWARE_DELIVERY_ARTIFACT_ORDER
)


def seed_software_delivery_workspace(
    service: ShipyardApplicationService,
    project_root: Path,
    owner: str,
) -> ProjectWorkspace:
    """Create the deterministic software-delivery Workbench workspace.

    The owner is resolved through the service's trusted identity provider;
    the caller cannot smuggle a different owner through a request payload.
    ``project_root`` is checked here so a successful workspace seed always
    points at a project containing the assets used by the following step.
    """

    root = _project_root(project_root)
    _require_asset(root, _ASSET_SPECS[0])
    principal = _resolve_human(service, owner)
    return service.create_workspace(
        {
            "workspace_id": WORKSPACE_ID,
            "project_id": PROJECT_ID,
            "name": "Software delivery requirements and delivery forecast",
            "domain_pack": "software_delivery",
            "current_phase": "intake",
        },
        principal,
    )


def seed_software_delivery_artifacts(
    service: ShipyardApplicationService,
    workspace_id: str,
    owner: str,
) -> list[Artifact]:
    """Register the checked-in vertical-slice assets through the Service.

    The repository root is intentionally resolved from this package for the
    public three-argument interface.  The CLI and tests both run from the
    repository checkout, while ``_asset_root`` keeps the path deterministic
    when the command is invoked from another current directory.
    """

    workspace = service.get_workspace(workspace_id)
    if workspace.project_id != PROJECT_ID:
        raise ValueError(
            f"workspace {workspace_id} is not the software-delivery project"
        )
    principal = _resolve_human(service, owner)
    root = _asset_root()
    artifacts: list[Artifact] = []
    previous_artifact_id: str | None = None
    for spec in _ASSET_SPECS:
        path = _require_asset(root, spec)
        artifact_id = f"artifact:{PROJECT_ID}:{spec.key}"
        artifact = _build_artifact(
            spec,
            path,
            artifact_id=artifact_id,
            owner=principal.subject,
            parent_artifact_id=previous_artifact_id,
        )
        saved = service.register_artifact(workspace_id, artifact, principal)
        artifacts.append(saved)
        previous_artifact_id = saved.artifact_id
    return artifacts


def run_workbench_gate_snapshot(
    service: ShipyardApplicationService,
    workspace_id: str,
    artifact_ids: list[str] | tuple[str, ...],
    *,
    project_root: Path | None = None,
) -> list[GateReviewSnapshot]:
    """Run the deterministic sandbox pipeline and return unpersisted snapshots.

    Returning snapshots instead of writing them is intentional: the caller
    must use ``service.record_gate_review`` with the bound system gate-runner
    identity.  This preserves the Service-only mutation boundary and lets a
    human review or replace a snapshot before it enters the append-only gate
    history.
    """

    workspace = service.get_workspace(workspace_id)
    requested_ids = _normalize_artifact_ids(artifact_ids)
    snapshot = service.get_workspace_snapshot(workspace_id)
    artifacts_by_id = {
        artifact.artifact_id: artifact for artifact in snapshot["artifacts"]
    }
    missing = sorted(set(requested_ids) - set(artifacts_by_id))
    available_ids = [
        artifact_id
        for artifact_id in sorted(requested_ids)
        if artifact_id in artifacts_by_id
    ]
    # A GateReviewSnapshot must contain at least one real Artifact hash.  If
    # every requested input is absent, there is no honest snapshot to create;
    # fail closed rather than manufacturing a hash for an unregistered input.
    if not available_ids:
        raise RecordNotFoundError(
            "cannot create gate snapshot without a registered Artifact: "
            + ", ".join(missing)
        )
    artifacts = [artifacts_by_id[artifact_id] for artifact_id in available_ids]
    source_root = _asset_root()
    source_violations: list[str] = []
    if missing:
        source_violations.append(
            "missing registered Artifact(s): " + ", ".join(missing)
        )
    if set(requested_ids) != SOFTWARE_DELIVERY_ARTIFACT_IDS:
        source_violations.append(
            "software-delivery Gate snapshot must cover all six seeded Artifacts"
        )
    if project_root is not None:
        try:
            requested_root = _project_root(project_root)
        except FileNotFoundError:
            requested_root = None
            source_violations.append("requested source root does not exist")
        if requested_root is not None and requested_root != source_root:
            source_violations.append(
                "requested source root cannot switch the registered source snapshot"
            )
    return build_software_delivery_gate_reviews(
        workspace.workspace_id,
        service.required_gate_ids,
        artifacts,
        source_root=source_root,
        extra_violations=source_violations,
    )


def _project_root(value: Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"software-delivery project root does not exist: {root}")
    return root


def _asset_root() -> Path:
    return Path(__file__).resolve().parents[3] / "projects" / PROJECT_ID


def _require_asset(root: Path, spec: _AssetSpec) -> Path:
    path = root / spec.relative_path
    if not path.is_file():
        raise FileNotFoundError(f"missing software-delivery asset: {path}")
    return path


def _resolve_human(service: ShipyardApplicationService, owner: str) -> Principal:
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner must not be blank")
    try:
        principal = service.identity_provider.resolve({"subject": owner.strip()})
    except (KeyError, PermissionError, UnauthorizedError) as exc:
        raise UnauthorizedError(f"unknown or unbound human owner: {owner}") from exc
    if principal.kind != "human":
        raise UnauthorizedError("software-delivery seed owner must be a human")
    return principal


def _normalize_artifact_ids(artifact_ids: list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(artifact_ids, str):
        raise TypeError("artifact_ids must be a sequence of strings")
    normalized = list(dict.fromkeys(artifact_ids))
    if not normalized or any(not isinstance(item, str) or not item.strip() for item in normalized):
        raise ValueError("artifact_ids must contain at least one non-blank ID")
    return [item.strip() for item in normalized]


def _build_artifact(
    spec: _AssetSpec,
    path: Path,
    *,
    artifact_id: str,
    owner: str,
    parent_artifact_id: str | None,
) -> Artifact:
    raw_bytes = path.read_bytes()
    source_sha256 = sha256(raw_bytes).hexdigest()
    source_ref = f"source:{PROJECT_ID}/{spec.relative_path}"
    document = _read_document(raw_bytes, spec)
    content: dict[str, Any] = {
        "source_ref": source_ref,
        "format": spec.format,
        "document": document,
    }
    dependencies = [parent_artifact_id] if parent_artifact_id else []
    return Artifact.build(
        artifact_id=artifact_id,
        project_id=PROJECT_ID,
        kind=spec.kind,
        version="1.0.0",
        status="draft",
        owner=owner,
        content=content,
        depends_on=dependencies,
        evidence_refs=[source_ref],
        metadata={
            "source_path": spec.relative_path,
            "source_sha256": source_sha256,
            "seed_version": SEED_VERSION,
        },
        parent_artifact_ids=dependencies,
        producer=SEED_PRODUCER,
        created_at=SEED_CREATED_AT,
        validation_results=[
            {
                "validator": "shipyard-seed.source-integrity",
                "version": "1.0.0",
                "passed": True,
                "source_sha256": source_sha256,
            }
        ],
    )


def _read_document(raw_bytes: bytes, spec: _AssetSpec) -> Any:
    text = raw_bytes.decode("utf-8")
    if spec.format == "turtle":
        return text
    document = yaml.safe_load(text)
    return {} if document is None else document


__all__ = [
    "run_workbench_gate_snapshot",
    "seed_software_delivery_artifacts",
    "seed_software_delivery_workspace",
]

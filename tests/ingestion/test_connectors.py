from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from aifde.builder.sources import SourceRegistry
from aifde.ingestion.connectors import (
    CaptureRequest,
    ConnectorRegistry,
    LocalFileConnector,
)


UTC = timezone.utc


def _request() -> CaptureRequest:
    return CaptureRequest(
        version="2026-08-14",
        observed_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
        available_at=datetime(2026, 8, 14, 10, tzinfo=UTC),
        extraction_version="local-file-v1",
    )


def test_local_file_connector_captures_content_and_registers_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "orders.json"
    path.write_text(json.dumps({"orders": [{"id": "PO-1"}]}), encoding="utf-8")
    registry = SourceRegistry()
    connector = LocalFileConnector.from_path(
        path,
        owner="procurement",
        authority_level=5,
        classification="internal",
        access_policy_id="policy:procurement",
        registry=registry,
    )

    descriptor = connector.describe()
    snapshot = connector.capture(_request())

    assert descriptor.source_type == "json"
    assert descriptor.connector_version == "local-file-v1"
    assert snapshot.content_hash
    assert registry.get_snapshot(snapshot.snapshot_id) == snapshot


def test_connector_registry_rejects_conflicting_identity(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("one\n", encoding="utf-8")
    connector = LocalFileConnector.from_path(
        path,
        owner="procurement",
        authority_level=3,
        classification="internal",
        access_policy_id="policy:procurement",
    )
    registry = ConnectorRegistry()
    registry.register(connector)
    registry.register(connector)

    with pytest.raises(ValueError, match="immutable"):
        other = LocalFileConnector.from_path(
            path,
            owner="other-owner",
            authority_level=3,
            classification="internal",
            access_policy_id="policy:procurement",
        )
        registry.register(other)


def test_local_file_connector_fails_closed_for_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"binary")

    with pytest.raises(ValueError, match="unsupported source type"):
        LocalFileConnector.from_path(
            path,
            owner="procurement",
            authority_level=3,
            classification="internal",
            access_policy_id="policy:procurement",
        )


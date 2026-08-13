from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from aifde.builder.contracts import EvidenceFragment, SourceAsset, SourceSnapshot
from aifde.builder.sources import SourceRegistry


FIXTURES = Path(__file__).parent / "fixtures"


def dt(hour: int) -> datetime:
    return datetime(2026, 8, 13, hour, tzinfo=timezone.utc)


def make_asset() -> SourceAsset:
    return SourceAsset.register(
        "erp-purchase-orders",
        "fixture://purchase-orders.json",
        "json",
        "procurement",
        5,
        "internal",
        "policy:procurement",
        "schema-v1",
        {},
    )


@pytest.fixture
def registry() -> SourceRegistry:
    return SourceRegistry()


def test_snapshot_hash_and_fragment_locator_are_stable(registry: SourceRegistry):
    asset = registry.register(make_asset())
    snapshot = registry.capture(
        asset.source_asset_id,
        "2026-08-13",
        b'{"po_id":"PO-001"}',
        observed_at=dt(9),
        available_at=dt(10),
        extraction_version="raw-v1",
    )

    fragment = registry.slice(snapshot.snapshot_id, "$.orders[0]", '{"po_id":"PO-001"}')

    assert snapshot.content_hash == sha256(b'{"po_id":"PO-001"}').hexdigest()
    assert snapshot.content_hash == fragment.source_content_hash
    assert fragment.locator == "$.orders[0]"
    assert fragment.evidence_id.startswith("evidence:")


def test_source_snapshot_is_append_only(registry: SourceRegistry):
    asset = registry.register(make_asset())
    first = registry.capture(asset.source_asset_id, "v1", b"one", dt(9), dt(9), "raw-v1")

    with pytest.raises(ValueError, match="immutable"):
        registry.capture(asset.source_asset_id, "v1", b"changed", dt(9), dt(9), "raw-v1")

    assert registry.get_snapshot(first.snapshot_id).content_hash == sha256(b"one").hexdigest()


def test_same_snapshot_capture_is_idempotent(registry: SourceRegistry):
    asset = registry.register(make_asset())
    first = registry.capture(asset.source_asset_id, "v1", b"one", dt(9), dt(9), "raw-v1")
    second = registry.capture(asset.source_asset_id, "v1", b"one", dt(9), dt(9), "raw-v1")

    assert second == first


def test_contracts_are_frozen_and_reject_naive_times_and_blank_locations():
    with pytest.raises(ValidationError):
        SourceAsset.register(" ", "fixture://x", "json", "owner", 1, "internal", "p", "s", {})

    with pytest.raises(ValidationError):
        SourceSnapshot(
            snapshot_id="snapshot:1",
            source_asset_id="asset-1",
            version="v1",
            content=b"x",
            content_hash=sha256(b"x").hexdigest(),
            observed_at=datetime(2026, 8, 13, 9),
            available_at=dt(9),
            extraction_version="raw-v1",
        )

    with pytest.raises(ValidationError):
        EvidenceFragment.from_snapshot(
            SourceSnapshot.capture(make_asset(), "v1", b"x", dt(9), dt(9), "raw-v1"),
            " ",
            "x",
        )


def test_registry_returns_defensive_copies_and_preserves_both_evidence_texts(
    registry: SourceRegistry,
):
    asset = registry.register(make_asset())
    snapshot = registry.capture(asset.source_asset_id, "v1", b"source", dt(9), dt(9), "raw-v1")
    fragment = registry.slice(
        snapshot.snapshot_id,
        "line:1",
        "Promised date: 2026-09-01",
        normalized_content="promised date: 2026-09-01",
        extraction_method="markdown",
        event_time=dt(8),
        confidence=0.9,
    )

    returned = registry.get_fragment(fragment.evidence_id)
    with pytest.raises(ValidationError):
        returned.content = "changed"
    assert returned.content == "Promised date: 2026-09-01"
    assert returned.normalized_content == "promised date: 2026-09-01"

    listed = registry.list_fragments()
    assert listed == [fragment]
    assert listed is not registry.list_fragments()


def test_supplier_fixtures_capture_overlapping_sources_with_original_locations(
    registry: SourceRegistry,
):
    json_content = (FIXTURES / "supplier_purchase_orders.json").read_bytes()
    notes_content = (FIXTURES / "supplier_notes.md").read_bytes()
    asset_json = registry.register(
        SourceAsset.register(
            "erp-purchase-orders",
            "fixture://supplier_purchase_orders.json",
            "json",
            "procurement",
            5,
            "internal",
            "policy:procurement",
            "purchase-order-v1",
            {"format": "json"},
        )
    )
    asset_notes = registry.register(
        SourceAsset.register(
            "procurement-notes",
            "fixture://supplier_notes.md",
            "markdown",
            "procurement",
            3,
            "internal",
            "policy:procurement",
            "notes-v1",
            {"format": "markdown"},
        )
    )
    json_snapshot = registry.capture(asset_json.source_asset_id, "2026-08-13", json_content, dt(9), dt(10), "raw-v1")
    notes_snapshot = registry.capture(asset_notes.source_asset_id, "2026-08-13", notes_content, dt(11), dt(12), "raw-v1")

    po_fragment = registry.slice(json_snapshot.snapshot_id, "$.purchase_orders[0]", '{"supplier":"Acme Industrial","promised_date":"2026-09-01"}')
    note_fragment = registry.slice(notes_snapshot.snapshot_id, "line:3-4", "Acme Industries promised date changed to 2026-09-05.")

    assert po_fragment.snapshot_id == json_snapshot.snapshot_id
    assert po_fragment.locator == "$.purchase_orders[0]"
    assert note_fragment.snapshot_id == notes_snapshot.snapshot_id
    assert note_fragment.locator == "line:3-4"
    assert "Acme Industrial" in json_content.decode()
    assert "Acme Industries" in notes_content.decode()
    assert "2026-09-05" in notes_content.decode()

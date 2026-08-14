from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from aifde.builder.sources import SourceRegistry
from aifde.ingestion.connectors import CaptureRequest, LocalFileConnector
from aifde.ingestion.extractors import EvidenceExtractor
from aifde.ingestion.quality import DataProductContract, DataQualityEngine


UTC = timezone.utc


def _capture(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    registry = SourceRegistry()
    connector = LocalFileConnector.from_path(
        path,
        owner="procurement",
        authority_level=5,
        classification="internal",
        access_policy_id="policy:procurement",
        registry=registry,
    )
    snapshot = connector.capture(
        CaptureRequest(
            version="v1",
            observed_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
            available_at=datetime(2026, 8, 14, 10, tzinfo=UTC),
            extraction_version="extractor-v1",
        )
    )
    return snapshot


def test_json_extractor_keeps_replayable_jsonpath_fragments(tmp_path) -> None:
    snapshot = _capture(
        tmp_path,
        "orders.json",
        json.dumps({"orders": [{"id": "PO-1"}, {"id": "PO-2"}]}),
    )

    report = EvidenceExtractor().extract(snapshot)

    assert report.passed is True
    assert [item.locator for item in report.fragments] == [
        "$.orders[0]",
        "$.orders[1]",
    ]
    assert all(item.source_content_hash == snapshot.content_hash for item in report.fragments)


def test_csv_and_markdown_extractors_keep_physical_locations(tmp_path) -> None:
    csv_snapshot = _capture(tmp_path, "orders.csv", "id,supplier\nPO-1,ACME\n")
    md_snapshot = _capture(tmp_path, "notes.md", "# Notes\nSupplier delay\n")

    csv_report = EvidenceExtractor().extract(csv_snapshot)
    md_report = EvidenceExtractor().extract(md_snapshot)

    assert csv_report.fragments[1].locator == "csv:row:2"
    assert csv_report.fragments[1].content == "PO-1,ACME"
    assert md_report.fragments[1].locator == "line:2"
    assert md_report.fragments[1].content == "Supplier delay"


def test_quality_engine_checks_required_unique_and_null_fields() -> None:
    contract = DataProductContract(
        product_id="orders",
        version="1.0.0",
        grain="purchase_order",
        unique_key="po_id",
        required_fields=("po_id", "supplier_id"),
        max_null_ratio=0.0,
    )
    report = DataQualityEngine().run(
        [
            {"po_id": "PO-1", "supplier_id": "supplier:1"},
            {"po_id": "PO-1", "supplier_id": None},
        ],
        contract,
    )

    assert report.passed is False
    assert any("duplicate" in item for item in report.violations)
    assert any("null" in item for item in report.violations)


def test_quality_engine_rejects_unknown_contract_rows() -> None:
    contract = DataProductContract(
        product_id="orders",
        version="1.0.0",
        grain="purchase_order",
        unique_key="po_id",
        required_fields=("po_id",),
    )

    with pytest.raises(TypeError, match="mapping"):
        DataQualityEngine().run(["not-a-row"], contract)


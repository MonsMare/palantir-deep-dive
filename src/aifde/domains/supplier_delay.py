"""Supplier-delay Domain Pack.

This module owns procurement vocabulary, source layout, identity policy, and
the legacy-compatible compiler adapter.  The platform Builder only sees the
``DomainCapture``/provider/compiler protocols.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence

from aifde.builder.compiler import MappingCompiler
from aifde.builder.contracts import SourceAsset, SourceSnapshot
from aifde.builder.semantic import DeterministicCandidateProvider
from aifde.builder.sources import SourceRegistry
from aifde.platform.domain_pack import DomainPack
from aifde.platform.ontology_ir import (
    ClassIR,
    EventIR,
    MetricIR,
    OntologyIR,
    PropertyIR,
    RelationshipIR,
    StateIR,
)

from .base import DomainCapture


_PACK_EVIDENCE = "domain-pack:supplier-delay@1.0.0"


def _supplier_ontology() -> OntologyIR:
    classes = tuple(
        ClassIR(name=name, label=label, evidence_refs=(_PACK_EVIDENCE,), version="1.0.0", status="accepted")
        for name, label in (
            ("Supplier", "Supplier"),
            ("PurchaseOrder", "Purchase Order"),
            ("PurchaseOrderLine", "Purchase Order Line"),
            ("PromisedDelivery", "Promised Delivery"),
            ("PromisedDateRevision", "Promised Date Revision"),
            ("DeliveryEvent", "Delivery Event"),
            ("DeliveryException", "Delivery Exception"),
        )
    )
    properties = tuple(
        PropertyIR(
            name=name,
            label=label,
            domain=domain,
            value_type=value_type,
            range=range_name,
            min_count=min_count,
            evidence_refs=(_PACK_EVIDENCE,),
            version="1.0.0",
            status="accepted",
        )
        for name, label, domain, value_type, range_name, min_count in (
            ("supplierId", "Supplier ID", "Supplier", "string", None, 1),
            ("purchaseOrderId", "Purchase Order ID", "PurchaseOrder", "string", None, 1),
            ("lineId", "Line ID", "PurchaseOrderLine", "string", None, 1),
            ("sku", "SKU", "PurchaseOrderLine", "string", None, 1),
            ("quantity", "Quantity", "PurchaseOrderLine", "number", None, 1),
            ("promisedDeliveryDate", "Promised Delivery Date", "PurchaseOrder", "date", None, 1),
            ("promisedDate", "Promised Date", "PromisedDelivery", "date", None, 1),
            ("actualDeliveryDate", "Actual Delivery Date", "DeliveryEvent", "date", None, 1),
            ("delayState", "Delay State", "PurchaseOrder", "string", None, 1),
            ("delayDays", "Delay Days", "PurchaseOrder", "integer", None, 0),
            ("eventTime", "Event Time", "DeliveryEvent", "date", None, 1),
        )
    )
    relationships = tuple(
        RelationshipIR(
            name=name,
            label=label,
            source=source,
            target=target,
            min_count=min_count,
            evidence_refs=(_PACK_EVIDENCE,),
            version="1.0.0",
            status="accepted",
        )
        for name, label, source, target, min_count in (
            ("hasSupplier", "Has Supplier", "PurchaseOrder", "Supplier", 1),
            ("hasLine", "Has Line", "PurchaseOrder", "PurchaseOrderLine", 1),
            ("hasPromisedDelivery", "Has Promised Delivery", "PurchaseOrder", "PromisedDelivery", 1),
            ("hasDateRevision", "Has Date Revision", "PurchaseOrder", "PromisedDateRevision", 0),
            ("hasDeliveryEvent", "Has Delivery Event", "PurchaseOrder", "DeliveryEvent", 0),
            ("hasException", "Has Exception", "PurchaseOrder", "DeliveryException", 0),
            ("forPurchaseOrder", "For Purchase Order", "DeliveryEvent", "PurchaseOrder", 1),
            ("affects", "Affects", "DeliveryException", "PurchaseOrder", 1),
        )
    )
    return OntologyIR(
        ontology_id="supplier-delay",
        version="1.0.0",
        namespace="urn:aifde:supplier-delay:",
        classes=classes,
        properties=properties,
        relationships=relationships,
        events=(
            EventIR(
                name="DeliveryObserved",
                label="Delivery Event",
                subject="PurchaseOrder",
                event_time_field="actualDeliveryDate",
                evidence_refs=(_PACK_EVIDENCE,),
                version="1.0.0",
                status="accepted",
            ),
            EventIR(
                name="PromisedDateChanged",
                label="Promised Date Revision",
                subject="PurchaseOrder",
                event_time_field="revisionDate",
                evidence_refs=(_PACK_EVIDENCE,),
                version="1.0.0",
                status="accepted",
            ),
        ),
        states=(
            StateIR(
                name="DelayState",
                label="Delay State",
                subject="PurchaseOrder",
                values=("Unknown", "OnTime", "AtRisk", "Delayed"),
                evidence_refs=(_PACK_EVIDENCE,),
                version="1.0.0",
                status="accepted",
            ),
        ),
        metrics=(
            MetricIR(
                name="delayDaysMetric",
                label="Delay Days",
                subject="PurchaseOrder",
                expression="max(0, actualDeliveryDate - promisedDeliveryDate)",
                time_grain="purchase_order",
                evidence_refs=(_PACK_EVIDENCE,),
                version="1.0.0",
                status="accepted",
            ),
        ),
        evidence_refs=(_PACK_EVIDENCE,),
        status="accepted",
    )


def _supplier_pack() -> DomainPack:
    return DomainPack(
        pack_id="supplier-delay",
        version="1.0.0",
        domain="procurement",
        vocabulary={
            "supplier": "Supplier",
            "purchase order": "PurchaseOrder",
            "promised date": "PromisedDeliveryDate",
            "delivery event": "DeliveryEvent",
            "delay state": "DelayState",
        },
        ontology=_supplier_ontology(),
        mappings=(
            {
                "mapping_id": "supplier.purchase_order.supplier",
                "source_field_path": "$.purchase_orders[*].supplier",
                "target_product": "purchase_order",
                "target_grain": "purchase_order",
                "target_field": "supplier_id",
                "identity_rule": "supplier canonical entity resolution",
                "time_semantics": "observed_at/available_at",
            },
            {
                "mapping_id": "supplier.purchase_order.promised_date",
                "source_field_path": "$.purchase_orders[*].promised_date",
                "target_product": "purchase_order",
                "target_grain": "purchase_order",
                "target_field": "promised_delivery_date",
                "identity_rule": "purchase order external key",
                "time_semantics": "valid_time",
            },
        ),
        computation={
            "feature_grain": "purchase_order",
            "delay_state_expression": "actual_delivery_date > promised_delivery_date",
        },
        decisions={"high_impact_entity_types": ("supplier",)},
        actions={"default_adapter": "mock-procurement-webhook"},
        acceptance_suite={
            "primary_key": "purchase_order_id",
            "target_product": "purchase_order",
            "target_grain": "purchase_order",
            "required_fields": ("supplier_id", "promised_delivery_date"),
            "business_exception_predicates": ("actualDeliveryDate",),
        },
    )


class SupplierDelayDomain:
    """Pack adapter preserving the existing procurement behavior."""

    def __init__(self) -> None:
        self.pack = _supplier_pack()
        self._provider = DeterministicCandidateProvider()
        self._compiler = MappingCompiler()

    @property
    def provider(self):
        return self._provider

    @property
    def compiler(self):
        return self._compiler

    def capture(self, source_paths: Sequence[str]) -> DomainCapture:
        if len(source_paths) != 2:
            raise ValueError("supplier-delay Domain Pack requires exactly two source paths")
        json_path = Path(source_paths[0])
        notes_path = Path(source_paths[1])
        if not json_path.exists() or not notes_path.exists():
            raise FileNotFoundError("supplier-delay source path does not exist")
        root = json_path.parent.parent
        registry = SourceRegistry()
        json_asset = registry.register(
            SourceAsset.register(
                "erp-purchase-orders",
                f"file://{json_path.as_posix()}",
                "json",
                "procurement",
                5,
                "internal",
                "policy:procurement",
                "purchase-order-v1",
                {"format": "json", "project_root": str(root)},
            )
        )
        notes_asset = registry.register(
            SourceAsset.register(
                "procurement-notes",
                f"file://{notes_path.as_posix()}",
                "markdown",
                "procurement",
                3,
                "internal",
                "policy:procurement",
                "notes-v1",
                {"format": "markdown", "project_root": str(root)},
            )
        )
        json_snapshot = registry.capture(
            json_asset.source_asset_id,
            "2026-08-13",
            json_path.read_bytes(),
            datetime(2026, 8, 13, 9, tzinfo=timezone.utc),
            datetime(2026, 8, 13, 10, tzinfo=timezone.utc),
            "raw-v1",
        )
        notes_snapshot = registry.capture(
            notes_asset.source_asset_id,
            "2026-09-08",
            notes_path.read_bytes(),
            datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
            datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
            "raw-v1",
        )
        document = json.loads(json_path.read_text(encoding="utf-8"))
        orders = document.get("purchase_orders", [])
        fragments = [
            registry.slice(
                json_snapshot.snapshot_id,
                f"$.purchase_orders[{index}]",
                json.dumps(order, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
            for index, order in enumerate(orders)
        ]
        fragments.append(
            registry.slice(
                notes_snapshot.snapshot_id,
                "line:3-5",
                "\n".join(notes_path.read_text(encoding="utf-8").splitlines()[2:5]),
                event_time=datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
            )
        )
        return DomainCapture(
            registry=registry,
            fragments=tuple(fragments),
            snapshots=(json_snapshot, notes_snapshot),
        )


__all__ = ["SupplierDelayDomain"]

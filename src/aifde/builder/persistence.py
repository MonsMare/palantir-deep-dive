"""Append-only persistence for production Builder provenance and releases."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from aifde.observability.audit import AuditEvent
from aifde.registry.sqlite import SQLiteRegistry

from .compiler import CompileResult
from .gates import OntologyReleasePackage


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _persist_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _persist_jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"encoding": "base64", "sha256": sha256(bytes(value)).hexdigest(), "size": len(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return _persist_jsonable(value.model_dump(mode="python"))
    if is_dataclass(value):
        return _persist_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _persist_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_persist_jsonable(item) for item in value]
    return value


def _model_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if is_dataclass(value):
        return asdict(value)
    return value


class BuilderRegistry(Protocol):
    """Minimal persistence boundary required by the production Builder."""

    def append_compile_result(self, result: CompileResult) -> str: ...

    def append_release_manifest(self, package: OntologyReleasePackage) -> str: ...

    def get_field_provenance(self, target_id: str, field_name: str) -> dict[str, Any]: ...

    def get_release_manifest(self, release_id: str) -> dict[str, Any]: ...

    def verify_release_manifest(self, release_id: str) -> bool: ...

    def verify_compile_hash(self, compile_hash: str) -> bool: ...

    def append_audit_event(self, event: AuditEvent) -> str: ...

    def list_audit_events(self) -> list[dict[str, Any]]: ...

    def verify_audit_events(self) -> bool: ...


class SQLiteBuilderRegistry:
    """Persist immutable Builder outputs in the existing SQLite registry."""

    def __init__(self, database: str | Path) -> None:
        self._registry = SQLiteRegistry(database)
        self._ensure_operational_schema()

    @property
    def connection(self) -> Any:
        return self._registry.connection

    def close(self) -> None:
        self._registry.close()

    def append_audit_event(self, event: AuditEvent) -> str:
        """Persist one immutable audit event with its chain hashes."""

        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        payload = _persist_jsonable(event.model_dump(mode="python"))
        payload_json = _canonical_json(payload)

        def insert() -> None:
            connection = self.connection
            existing = connection.execute(
                "SELECT sequence FROM builder_audit_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError("audit event is append-only and already persisted")
            last = connection.execute(
                "SELECT MAX(sequence) AS sequence FROM builder_audit_events"
            ).fetchone()
            expected_sequence = int(last["sequence"] or 0) + 1
            if event.sequence != expected_sequence:
                raise ValueError(
                    f"audit sequence must append at {expected_sequence}, got {event.sequence}"
                )
            connection.execute(
                """
                INSERT INTO builder_audit_events(
                    event_id, sequence, payload_json, payload_hash, chain_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.sequence,
                    payload_json,
                    event.payload_hash,
                    event.chain_hash,
                ),
            )

        self._registry._write(insert)
        return event.chain_hash

    def list_audit_events(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT payload_json FROM builder_audit_events ORDER BY sequence"
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def verify_audit_events(self) -> bool:
        events = self.list_audit_events()
        previous_hash = "0" * 64
        for expected_sequence, payload in enumerate(events, start=1):
            event = AuditEvent.model_validate(payload)
            if event.sequence != expected_sequence:
                raise ValueError("persisted audit sequence mismatch")
            if event.previous_hash != previous_hash:
                raise ValueError("persisted audit predecessor hash mismatch")
            if event.payload_hash != _payload_hash(event.payload):
                raise ValueError("persisted audit payload hash mismatch")
            expected_chain = _payload_hash(
                {
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "actor": event.actor,
                    "subject_id": event.subject_id,
                    "payload_hash": event.payload_hash,
                    "previous_hash": event.previous_hash,
                }
            )
            if event.chain_hash != expected_chain:
                raise ValueError("persisted audit chain hash mismatch")
            previous_hash = event.chain_hash
        return True

    def _ensure_operational_schema(self) -> None:
        def create() -> None:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS builder_audit_events(
                    event_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    chain_hash TEXT NOT NULL
                )
                """
            )

        self._registry._write(create)

    def append_compile_result(self, result: CompileResult) -> str:
        if not isinstance(result, CompileResult):
            raise TypeError("result must be a CompileResult")
        if not result.validation_report.passed:
            raise ValueError("cannot persist an unvalidated compile result")
        payload = {
            "ontology_version": result.ontology_candidate.version,
            "artifact_hashes": result.artifact_hashes,
            "ontology_turtle": result.ontology_turtle,
            "shapes_turtle": result.shapes_turtle,
            "data_turtle": result.data_turtle,
            "canonical_rows": result.canonical_rows,
            "canonical_line_rows": result.canonical_line_rows or [],
            "canonical_revision_rows": result.canonical_revision_rows or [],
            "provenance_rows": result.provenance_rows,
            "mapping_specs": result.mapping_specs,
            "proposal_evidence_refs": result.proposal_evidence_refs,
            "source_field_paths": result.source_field_paths,
            "artifact_manifest_id": result.artifact_manifest_id,
            "domain_pack_id": result.domain_pack_id,
            "primary_key_field": result.primary_key_field,
            "target_product": result.target_product,
            "target_grain": result.target_grain,
            "required_fields": result.required_fields,
        }
        payload = _persist_jsonable(payload)
        compile_hash = _payload_hash(payload)

        def insert() -> None:
            connection = self.connection
            if connection.execute(
                "SELECT 1 FROM builder_compile_runs WHERE compile_hash = ?",
                (compile_hash,),
            ).fetchone() is not None:
                raise ValueError("compile result is append-only and already persisted")
            connection.execute(
                """
                INSERT INTO builder_compile_runs(
                    compile_hash, ontology_version, artifact_hashes_json, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    compile_hash,
                    result.ontology_candidate.version,
                    _canonical_json(result.artifact_hashes),
                    _canonical_json(payload),
                ),
            )
            for row in result.canonical_rows:
                target_id = str(row.get(result.primary_key_field, row.get("entity_id", "")))
                if not target_id:
                    raise ValueError(
                        f"canonical row requires primary key {result.primary_key_field!r}"
                    )
                for field_name, provenance in row["field_provenance"].items():
                    field_payload = {
                        "target_id": target_id,
                        "field_name": field_name,
                        "value": provenance.value,
                        "observed_at": provenance.observed_at,
                        "available_at": provenance.available_at,
                        "event_time": provenance.event_time,
                        "valid_from": provenance.valid_from,
                        "field_provenance": provenance,
                        "compile_hash": compile_hash,
                    }
                    field_json = _canonical_json(field_payload)
                    try:
                        connection.execute(
                            """
                            INSERT INTO builder_field_provenance(
                                compile_hash, target_id, field_name, payload_json, payload_hash
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                compile_hash,
                                target_id,
                                field_name,
                                field_json,
                                _payload_hash(field_payload),
                            ),
                        )
                    except Exception as exc:
                        raise ValueError(
                            f"field provenance is append-only and already persisted: {target_id}/{field_name}"
                        ) from exc
            for revision in result.canonical_revision_rows or []:
                revision_target_id = revision.get(
                    result.primary_key_field, revision.get("purchase_order_id")
                )
                if revision_target_id is None:
                    raise ValueError(
                        f"revision requires primary key {result.primary_key_field!r}"
                    )
                revision_payload = _persist_jsonable(
                    {"compile_hash": compile_hash, "revision": revision}
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO builder_field_provenance(
                        compile_hash, target_id, field_name, payload_json, payload_hash
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        compile_hash,
                        str(revision_target_id),
                        f"revision:{revision['revision_id']}",
                        _canonical_json(revision_payload),
                        _payload_hash(revision_payload),
                    ),
                )

        self._registry._write(insert)
        return compile_hash

    def append_source_snapshot(self, snapshot: Any) -> str:
        """Persist a content-addressed source snapshot through SourceRegistry's shape."""

        required = ("snapshot_id", "source_asset_id", "version", "content_hash")
        if any(not hasattr(snapshot, field_name) for field_name in required):
            raise TypeError("snapshot must expose source snapshot identity and content hash")
        payload = _persist_jsonable(_model_payload(snapshot))
        snapshot_id = str(snapshot.snapshot_id)
        content_hash = str(snapshot.content_hash)

        def insert() -> None:
            connection = self.connection
            if connection.execute(
                "SELECT 1 FROM builder_source_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone() is not None:
                raise ValueError("source snapshot is append-only and already persisted")
            connection.execute(
                """
                INSERT INTO builder_source_snapshots(
                    snapshot_id, source_asset_id, version, content_hash, payload_json, payload_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    str(snapshot.source_asset_id),
                    str(snapshot.version),
                    content_hash,
                    _canonical_json(payload),
                    _payload_hash(payload),
                ),
            )

        self._registry._write(insert)
        return f"source-snapshot:{snapshot_id}"

    def append_release_manifest(self, package: OntologyReleasePackage) -> str:
        if not isinstance(package, OntologyReleasePackage):
            raise TypeError("package must be an OntologyReleasePackage")
        payload = _persist_jsonable(_model_payload(package))
        release_id = package.release_id
        payload_json = _canonical_json(payload)
        payload_hash = _payload_hash(payload)
        expected_artifacts = {
            "ontology": package.ontology_artifact_hash,
            "shapes": package.shape_artifact_hash,
            "mappings": package.mapping_artifact_hash,
            "canonical_product": package.canonical_product_artifact_hash,
            "provenance": package.provenance_artifact_hash,
            "canonical_rdf": package.canonical_rdf_artifact_hash,
        }

        def insert() -> None:
            connection = self.connection
            compile_rows = connection.execute(
                "SELECT artifact_hashes_json FROM builder_compile_runs"
            ).fetchall()
            if not any(
                all(json.loads(row["artifact_hashes_json"]).get(key) == value for key, value in expected_artifacts.items())
                for row in compile_rows
            ):
                raise ValueError("release manifest must reference a persisted compile result")
            if connection.execute(
                "SELECT 1 FROM builder_release_manifests WHERE release_id = ?",
                (release_id,),
            ).fetchone() is not None:
                raise ValueError("release manifest is append-only and already persisted")
            connection.execute(
                """
                INSERT INTO builder_release_manifests(
                    release_id, ontology_version, payload_json, payload_hash
                ) VALUES (?, ?, ?, ?)
                """,
                (release_id, package.ontology_version, payload_json, payload_hash),
            )

        self._registry._write(insert)
        return payload_hash

    def get_field_provenance(
        self, target_id: str, field_name: str, *, compile_hash: str | None = None
    ) -> dict[str, Any]:
        query = """
            SELECT payload_json, payload_hash
            FROM builder_field_provenance
            WHERE target_id = ? AND field_name = ?
        """
        parameters: tuple[Any, ...] = (target_id, field_name)
        if compile_hash is not None:
            query += " AND compile_hash = ?"
            parameters += (compile_hash,)
        query += " ORDER BY rowid DESC LIMIT 1"
        row = self.connection.execute(query, parameters).fetchone()
        if row is None:
            raise KeyError((target_id, field_name))
        payload = json.loads(row["payload_json"])
        if _payload_hash(payload) != row["payload_hash"]:
            raise ValueError("field provenance hash mismatch")
        return payload

    def get_release_manifest(self, release_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT payload_json, payload_hash
            FROM builder_release_manifests
            WHERE release_id = ?
            """,
            (release_id,),
        ).fetchone()
        if row is None:
            raise KeyError(release_id)
        payload = json.loads(row["payload_json"])
        if _payload_hash(payload) != row["payload_hash"]:
            raise ValueError("release manifest hash mismatch")
        return payload

    def verify_release_manifest(self, release_id: str) -> bool:
        payload = self.get_release_manifest(release_id)
        expected = {
            "ontology": payload["ontology_artifact_hash"],
            "shapes": payload["shape_artifact_hash"],
            "mappings": payload["mapping_artifact_hash"],
            "canonical_product": payload["canonical_product_artifact_hash"],
            "provenance": payload["provenance_artifact_hash"],
            "canonical_rdf": payload["canonical_rdf_artifact_hash"],
        }
        rows = self.connection.execute(
            "SELECT artifact_hashes_json FROM builder_compile_runs"
        ).fetchall()
        for row in rows:
            artifact_hashes = json.loads(row["artifact_hashes_json"])
            if all(artifact_hashes.get(key) == value for key, value in expected.items()):
                return True
        return False

    def verify_compile_hash(self, compile_hash: str) -> bool:
        row = self.connection.execute(
            "SELECT artifact_hashes_json, payload_json FROM builder_compile_runs WHERE compile_hash = ?",
            (compile_hash,),
        ).fetchone()
        if row is None:
            raise KeyError(compile_hash)
        payload = json.loads(row["payload_json"])
        if _payload_hash(payload) != compile_hash:
            raise ValueError("compile result hash mismatch")
        artifact_hashes = json.loads(row["artifact_hashes_json"])
        return isinstance(artifact_hashes, dict) and all(
            isinstance(value, str) and len(value) == 64
            for value in artifact_hashes.values()
        )


__all__ = ["BuilderRegistry", "SQLiteBuilderRegistry"]

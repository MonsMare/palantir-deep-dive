"""SQLite adapter for the append-only AI FDE registry."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from types import SimpleNamespace
from typing import Any, Callable, Iterator, TypeVar

from aifde.domain.artifacts import (
    Artifact,
    canonical_json_bytes,
    normalize_semantic_version,
    semantic_version_key,
)
from aifde.domain.evidence import Evidence
from aifde.shipyard.contracts import (
    AgentProposal,
    AuditEvent,
    DecisionCase,
    GateReviewSnapshot,
    ProjectWorkspace,
    ReleaseCandidate,
)
from aifde.shipyard.store import ShipyardStore


_T = TypeVar("_T")

# Legacy Artifact rows had no creation timestamp; this explicit UTC sentinel is
# written once during migration so reads never synthesize a new timestamp.
_LEGACY_ARTIFACT_CREATED_AT = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _canonical_json_text(value: Any) -> str:
    """Serialize values with the same strict canonical rules as artifacts."""
    try:
        return canonical_json_bytes(value).decode("utf-8")
    except ValueError as exc:
        raise ValueError("registry JSON fields must contain finite JSON values") from exc


class SQLiteRegistry:
    """A single-database registry with immutable artifact and evidence records."""

    def __init__(self, database: str | Path) -> None:
        self._lock = RLock()
        self._connection = sqlite3.connect(
            str(database), isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._closed = False
        self._active_transaction: _SQLiteRegistryTransaction | None = None
        self._initialize_schema()
        self.artifacts = _SQLiteArtifactRepository(self)
        self.evidence = _SQLiteEvidenceRepository(self)
        self.shipyard: ShipyardStore = _SQLiteShipyardRepository(self)

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the connection for operational inspection and migrations."""
        return self._connection

    def close(self) -> None:
        """Close the underlying database connection; repeated calls are safe."""
        with self._lock:
            if not self._closed:
                if self._active_transaction is not None:
                    self._active_transaction.rollback()
                elif self._connection.in_transaction:
                    self._connection.rollback()
                self._connection.close()
                self._closed = True

    def transaction(self) -> _SQLiteRegistryTransaction:
        """Begin an explicit transaction for atomic multi-repository writes."""
        with self._lock:
            self._ensure_open()
            if self._active_transaction is not None or self._connection.in_transaction:
                raise RuntimeError("a registry transaction is already active")
            self._connection.execute("BEGIN IMMEDIATE")
            transaction = _SQLiteRegistryTransaction(self)
            self._active_transaction = transaction
            return transaction

    def get_project(self, project_id: str) -> SimpleNamespace:
        """Return a minimal read model when any project-scoped record exists."""
        with self._lock:
            self._ensure_open()
            for table in (
                "artifacts",
                "artifact_versions",
                "stage_runs",
                "gate_runs",
                "approvals",
            ):
                row = self._connection.execute(
                    f"SELECT 1 FROM {table} WHERE project_id = ? LIMIT 1",
                    (project_id,),
                ).fetchone()
                if row is not None:
                    return SimpleNamespace(project_id=project_id)
            raise KeyError(project_id)

    def list_artifacts(self, project_id: str) -> list[SimpleNamespace]:
        """Return the latest semantic version of every project artifact."""
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT artifact_id, kind, version, status, content_hash
                FROM artifact_versions
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()
            latest: dict[str, sqlite3.Row] = {}
            for row in rows:
                artifact_id = str(row["artifact_id"])
                current = latest.get(artifact_id)
                if current is None or semantic_version_key(
                    str(row["version"])
                ) > semantic_version_key(str(current["version"])):
                    latest[artifact_id] = row
            return [
                SimpleNamespace(
                    artifact_id=row["artifact_id"],
                    kind=row["kind"],
                    version=row["version"],
                    status=row["status"],
                    content_hash=row["content_hash"],
                    updated_at=None,
                )
                for row in latest.values()
            ]

    def list_stages(self, project_id: str) -> list[SimpleNamespace]:
        """Return stage-run payloads as read-only query models."""
        return self._list_payload_models("stage_runs", project_id)

    def list_gates(self, project_id: str) -> list[SimpleNamespace]:
        """Return gate-run payloads as read-only query models."""
        return self._list_payload_models("gate_runs", project_id)

    def _list_payload_models(
        self, table: str, project_id: str
    ) -> list[SimpleNamespace]:
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                f"SELECT payload_json FROM {table} WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            models: list[SimpleNamespace] = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                if not isinstance(payload, dict):
                    raise ValueError(f"{table} payload_json must contain a JSON object")
                models.append(SimpleNamespace(**payload))
            return models

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            active_transaction = self._active_transaction
            if active_transaction is not None:
                active_transaction._ensure_active()
                try:
                    yield
                except BaseException:
                    active_transaction._abort()
                    raise
                return
            if self._connection.in_transaction:
                raise RuntimeError("registry has an unmanaged active transaction")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _write(self, operation: Callable[[], _T]) -> _T:
        with self._write_transaction():
            return operation()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("registry is closed")

    def _initialize_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                project_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                PRIMARY KEY (project_id, artifact_id)
            );

            CREATE TABLE IF NOT EXISTS artifact_versions (
                project_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                version TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                owner TEXT NOT NULL,
                content_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                depends_on_json TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                parent_artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                producer TEXT,
                created_at TEXT NOT NULL,
                validation_results_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (project_id, artifact_id, version),
                FOREIGN KEY (project_id, artifact_id)
                    REFERENCES artifacts(project_id, artifact_id)
            );

            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                source_uri TEXT NOT NULL,
                locator TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                classification TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_content (
                evidence_id TEXT PRIMARY KEY,
                content BLOB NOT NULL,
                FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
            );

            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stage_runs (
                stage_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gate_runs (
                gate_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_outcomes (
                action_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shipyard_workspaces (
                workspace_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (workspace_id, revision)
            );

            CREATE TABLE IF NOT EXISTS shipyard_decision_cases (
                case_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shipyard_proposals (
                proposal_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                workspace_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (proposal_id, revision)
            );

            CREATE TABLE IF NOT EXISTS shipyard_gate_reviews (
                gate_run_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                workspace_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shipyard_release_candidates (
                candidate_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                workspace_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shipyard_audit_events (
                event_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                actor_kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                predecessor_hash TEXT NOT NULL
            );
            """
        )
        self._ensure_column(
            "artifact_versions",
            "parent_artifact_ids_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        self._ensure_column("artifact_versions", "producer", "TEXT")
        self._ensure_column("artifact_versions", "created_at", "TEXT")
        self._ensure_column(
            "artifact_versions",
            "validation_results_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        self._connection.execute(
            """
            UPDATE artifact_versions
            SET created_at = ?
            WHERE created_at IS NULL
            """,
            (_LEGACY_ARTIFACT_CREATED_AT.isoformat(),),
        )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )


class _SQLiteRegistryTransaction:
    """Transaction handle that deliberately requires an explicit commit."""

    def __init__(self, registry: SQLiteRegistry) -> None:
        self._registry = registry
        self._complete = False
        self._aborted = False
        self.artifacts = _SQLiteArtifactRepository(registry, self)
        self.evidence = _SQLiteEvidenceRepository(registry, self)
        self.shipyard: ShipyardStore = _SQLiteShipyardRepository(registry, self)

    def __enter__(self) -> _SQLiteRegistryTransaction:
        self._ensure_active()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        if not self._complete:
            self.rollback()
        return False

    def commit(self) -> None:
        """Commit once; a failed transaction must be discarded by the caller."""
        with self._registry._lock:
            if self._aborted:
                raise RuntimeError("registry transaction is aborted")
            if self._complete:
                raise RuntimeError("registry transaction is already complete")
            self._ensure_active()
            self._registry.connection.commit()
            self._complete = True
            self._registry._active_transaction = None

    def rollback(self) -> None:
        """Discard all writes and make this transaction unusable."""
        self._abort()

    def _ensure_active(self) -> None:
        if self._aborted:
            raise RuntimeError("registry transaction is aborted")
        if self._complete or self._registry._active_transaction is not self:
            raise RuntimeError("registry transaction is no longer active")
        if not self._registry.connection.in_transaction:
            raise RuntimeError("registry transaction is no longer active")

    def _abort(self) -> None:
        with self._registry._lock:
            if self._complete:
                return
            if self._registry.connection.in_transaction:
                self._registry.connection.rollback()
            self._aborted = True
            self._complete = True
            if self._registry._active_transaction is self:
                self._registry._active_transaction = None


class _SQLiteArtifactRepository:
    def __init__(
        self,
        registry: SQLiteRegistry,
        transaction: _SQLiteRegistryTransaction | None = None,
    ) -> None:
        self._registry = registry
        self._transaction = transaction

    def put(self, artifact: Artifact) -> Artifact:
        """Insert a new version and reject all attempts to replace a version."""
        if self._transaction is not None:
            self._transaction._ensure_active()

        def insert() -> Artifact:
            connection = self._registry.connection
            existing = connection.execute(
                "SELECT kind FROM artifacts WHERE project_id = ? AND artifact_id = ?",
                (artifact.project_id, artifact.artifact_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO artifacts(project_id, artifact_id, kind) VALUES (?, ?, ?)",
                    (artifact.project_id, artifact.artifact_id, artifact.kind),
                )
            elif existing["kind"] != artifact.kind:
                raise ValueError("artifact identity is immutable")

            version_rows = connection.execute(
                """
                SELECT version FROM artifact_versions
                WHERE project_id = ? AND artifact_id = ?
                """,
                (artifact.project_id, artifact.artifact_id),
            ).fetchall()
            if any(row["version"] == artifact.version for row in version_rows):
                raise ValueError("artifact versions are immutable and append-only")
            if version_rows and semantic_version_key(artifact.version) <= max(
                semantic_version_key(str(row["version"])) for row in version_rows
            ):
                raise ValueError("artifact versions are immutable and append-only")

            try:
                connection.execute(
                    """
                    INSERT INTO artifact_versions(
                        project_id, artifact_id, version, kind, status, owner,
                        content_json, content_hash, depends_on_json, evidence_refs_json,
                        metadata_json, parent_artifact_ids_json, producer, created_at,
                        validation_results_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.project_id,
                        artifact.artifact_id,
                        artifact.version,
                        artifact.kind,
                        artifact.status,
                        artifact.owner,
                        _canonical_json_text(artifact.content),
                        artifact.content_hash,
                        _canonical_json_text(artifact.depends_on),
                        _canonical_json_text(artifact.evidence_refs),
                        _canonical_json_text(artifact.metadata),
                        _canonical_json_text(artifact.parent_artifact_ids),
                        artifact.producer,
                        artifact.created_at.isoformat(),
                        _canonical_json_text(artifact.validation_results),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("artifact versions are immutable") from exc
            return artifact

        return self._registry._write(insert)

    def get(
        self, project_id: str, artifact_id: str, version: str | None = None
    ) -> Artifact:
        query = """
            SELECT * FROM artifact_versions
            WHERE project_id = ? AND artifact_id = ?
        """
        parameters: tuple[Any, ...] = (project_id, artifact_id)
        if version is not None:
            version = normalize_semantic_version(version)
            query += " AND version = ?"
            parameters += (version,)
            row = self._registry.connection.execute(query, parameters).fetchone()
        else:
            rows = self._registry.connection.execute(query, parameters).fetchall()
            row = max(rows, key=lambda candidate: semantic_version_key(str(candidate["version"])), default=None)
        if row is None:
            raise KeyError((project_id, artifact_id, version))
        return self._artifact_from_row(row)

    def list_versions(self, project_id: str, artifact_id: str) -> list[Artifact]:
        rows = self._registry.connection.execute(
            """
            SELECT * FROM artifact_versions
            WHERE project_id = ? AND artifact_id = ?
            """,
            (project_id, artifact_id),
        ).fetchall()
        return [
            self._artifact_from_row(row)
            for row in sorted(rows, key=lambda candidate: semantic_version_key(str(candidate["version"])))
        ]

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> Artifact:
        values: dict[str, Any] = {
            "artifact_id": row["artifact_id"],
            "project_id": row["project_id"],
            "kind": row["kind"],
            "version": row["version"],
            "status": row["status"],
            "owner": row["owner"],
            "content": json.loads(row["content_json"]),
            "content_hash": row["content_hash"],
            "depends_on": json.loads(row["depends_on_json"]),
            "evidence_refs": json.loads(row["evidence_refs_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "parent_artifact_ids": json.loads(row["parent_artifact_ids_json"]),
            "producer": row["producer"],
            "validation_results": json.loads(row["validation_results_json"]),
        }
        if row["created_at"] is None:
            raise ValueError("stored artifact is missing created_at after schema migration")
        values["created_at"] = datetime.fromisoformat(row["created_at"])
        return Artifact.model_validate(values)


class _SQLiteEvidenceRepository:
    def __init__(
        self,
        registry: SQLiteRegistry,
        transaction: _SQLiteRegistryTransaction | None = None,
    ) -> None:
        self._registry = registry
        self._transaction = transaction

    def put(self, evidence: Evidence, content: bytes) -> Evidence:
        """Insert evidence once, deriving its hash from the original bytes."""
        if self._transaction is not None:
            self._transaction._ensure_active()

        def insert() -> Evidence:
            if not isinstance(content, bytes):
                raise TypeError("evidence content must be bytes")
            saved = evidence.model_copy(update={"content_hash": sha256(content).hexdigest()})
            connection = self._registry.connection
            try:
                connection.execute(
                    """
                    INSERT INTO evidence(
                        evidence_id, source_uri, locator, content_hash, captured_at,
                        classification, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        saved.evidence_id,
                        saved.source_uri,
                        saved.locator,
                        saved.content_hash,
                        saved.captured_at.isoformat(),
                        saved.classification,
                        _canonical_json_text(saved.metadata),
                    ),
                )
                connection.execute(
                    "INSERT INTO evidence_content(evidence_id, content) VALUES (?, ?)",
                    (saved.evidence_id, content),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("evidence records are immutable") from exc
            return saved

        return self._registry._write(insert)

    def get(self, evidence_id: str) -> Evidence:
        row = self._registry.connection.execute(
            """
            SELECT evidence.*, evidence_content.content
            FROM evidence JOIN evidence_content USING (evidence_id)
            WHERE evidence_id = ?
            """,
            (evidence_id,),
        ).fetchone()
        if row is None:
            raise KeyError(evidence_id)
        self._verify_hash(row["content_hash"], row["content"])
        return Evidence.model_validate(
            {
                "evidence_id": row["evidence_id"],
                "source_uri": row["source_uri"],
                "locator": row["locator"],
                "content_hash": row["content_hash"],
                "captured_at": datetime.fromisoformat(row["captured_at"]),
                "classification": row["classification"],
                "metadata": json.loads(row["metadata_json"]),
            }
        )

    def read_content(self, evidence_id: str) -> bytes:
        row = self._registry.connection.execute(
            """
            SELECT evidence.content_hash, evidence_content.content
            FROM evidence JOIN evidence_content USING (evidence_id)
            WHERE evidence_id = ?
            """,
            (evidence_id,),
        ).fetchone()
        if row is None:
            raise KeyError(evidence_id)
        content = bytes(row["content"])
        self._verify_hash(row["content_hash"], content)
        return content

    @staticmethod
    def _verify_hash(expected_hash: str, content: bytes) -> None:
        if sha256(content).hexdigest() != expected_hash:
            raise ValueError("stored evidence content hash does not match original bytes")


class _SQLiteShipyardRepository:
    """SQLite implementation of the append-only Workbench store."""

    def __init__(
        self,
        registry: SQLiteRegistry,
        transaction: _SQLiteRegistryTransaction | None = None,
    ) -> None:
        self._registry = registry
        self._transaction = transaction

    def _read(self, operation: Callable[[], _T]) -> _T:
        with self._registry._lock:
            self._registry._ensure_open()
            if self._transaction is not None:
                self._transaction._ensure_active()
            return operation()

    def _write(self, operation: Callable[[], _T]) -> _T:
        if self._transaction is not None:
            self._transaction._ensure_active()
        return self._registry._write(operation)

    @staticmethod
    def _prepare(
        value: Any,
        expected_type: type[Any],
        record_name: str,
    ) -> tuple[Any, str]:
        if not isinstance(value, expected_type):
            raise TypeError(f"{record_name} must be a {expected_type.__name__}")
        saved = expected_type.model_validate(value.model_dump(mode="json"))
        return saved, _canonical_json_text(saved.model_dump(mode="json"))

    @staticmethod
    def _payload_model(row: sqlite3.Row, expected_type: type[Any], record_name: str) -> Any:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"stored {record_name} payload is not valid JSON") from exc
        saved = expected_type.model_validate(payload)
        if _canonical_json_text(saved.model_dump(mode="json")) != row["payload_json"]:
            raise ValueError(f"stored {record_name} payload is not canonical")
        return saved

    @classmethod
    def _workspace_from_row(cls, row: sqlite3.Row) -> ProjectWorkspace:
        workspace = cls._payload_model(row, ProjectWorkspace, "workspace")
        if (
            row["workspace_id"] != workspace.workspace_id
            or int(row["revision"]) != workspace.revision
            or row["project_id"] != workspace.project_id
            or row["created_at"] != workspace.created_at.isoformat()
            or row["updated_at"] != workspace.updated_at.isoformat()
        ):
            raise ValueError("stored workspace identity or timestamp does not match payload")
        return workspace

    @classmethod
    def _decision_case_from_row(cls, row: sqlite3.Row) -> DecisionCase:
        decision_case = cls._payload_model(row, DecisionCase, "decision case")
        if row["case_id"] != decision_case.case_id or row["workspace_id"] != decision_case.workspace_id:
            raise ValueError("stored decision case identity does not match payload")
        return decision_case

    @classmethod
    def _proposal_from_row(cls, row: sqlite3.Row) -> AgentProposal:
        proposal = cls._payload_model(row, AgentProposal, "proposal")
        if (
            row["proposal_id"] != proposal.proposal_id
            or int(row["revision"]) != proposal.revision
            or row["workspace_id"] != proposal.workspace_id
            or row["content_hash"] != proposal.content_hash
            or row["created_at"] != proposal.created_at.isoformat()
        ):
            raise ValueError("stored proposal identity, hash, or timestamp does not match payload")
        return proposal

    @classmethod
    def _gate_review_from_row(cls, row: sqlite3.Row) -> GateReviewSnapshot:
        gate_review = cls._payload_model(row, GateReviewSnapshot, "gate review")
        if (
            row["gate_run_id"] != gate_review.gate_run_id
            or int(row["revision"]) != gate_review.revision
            or row["workspace_id"] != gate_review.workspace_id
            or row["content_hash"] != gate_review.content_hash
            or row["created_at"] != gate_review.created_at.isoformat()
        ):
            raise ValueError("stored gate review identity, hash, or timestamp does not match payload")
        return gate_review

    @classmethod
    def _release_candidate_from_row(cls, row: sqlite3.Row) -> ReleaseCandidate:
        candidate = cls._payload_model(row, ReleaseCandidate, "release candidate")
        if (
            row["candidate_id"] != candidate.candidate_id
            or int(row["revision"]) != candidate.revision
            or row["workspace_id"] != candidate.workspace_id
            or row["content_hash"] != candidate.content_hash
            or row["created_at"] != candidate.created_at.isoformat()
        ):
            raise ValueError(
                "stored release candidate identity, hash, or timestamp does not match payload"
            )
        return candidate

    @classmethod
    def _audit_event_from_row(cls, row: sqlite3.Row) -> AuditEvent:
        event = cls._payload_model(row, AuditEvent, "audit event")
        if (
            row["event_id"] != event.event_id
            or row["workspace_id"] != event.workspace_id
            or row["event_type"] != event.event_type
            or row["actor"] != event.actor
            or row["actor_kind"] != event.actor_kind
            or row["event_hash"] != event.event_hash
            or row["created_at"] != event.created_at.isoformat()
            or row["predecessor_hash"] != event.predecessor_hash
        ):
            raise ValueError("stored audit event identity, hash, or timestamp does not match payload")
        return event

    def put_workspace(self, workspace: ProjectWorkspace) -> ProjectWorkspace:
        def insert() -> ProjectWorkspace:
            saved, payload_json = self._prepare(workspace, ProjectWorkspace, "workspace")
            try:
                self._registry.connection.execute(
                    """
                    INSERT INTO shipyard_workspaces(
                        workspace_id, revision, project_id, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        saved.workspace_id,
                        saved.revision,
                        saved.project_id,
                        payload_json,
                        saved.created_at.isoformat(),
                        saved.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("workspace revision already exists") from exc
            return saved

        return self._write(insert)

    def get_workspace(self, workspace_id: str) -> ProjectWorkspace:
        def select() -> ProjectWorkspace:
            row = self._registry.connection.execute(
                """
                SELECT * FROM shipyard_workspaces
                WHERE workspace_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            if row is None:
                raise KeyError(workspace_id)
            return self._workspace_from_row(row)

        return self._read(select)

    def list_workspaces(self, workspace_id: str | None = None) -> list[ProjectWorkspace]:
        def select() -> list[ProjectWorkspace]:
            if workspace_id is None:
                rows = self._registry.connection.execute(
                    "SELECT * FROM shipyard_workspaces ORDER BY workspace_id, revision"
                ).fetchall()
            else:
                rows = self._registry.connection.execute(
                    """
                    SELECT * FROM shipyard_workspaces
                    WHERE workspace_id = ?
                    ORDER BY revision
                    """,
                    (workspace_id,),
                ).fetchall()
            return [self._workspace_from_row(row) for row in rows]

        return self._read(select)

    def put_decision_case(self, decision_case: DecisionCase) -> DecisionCase:
        def insert() -> DecisionCase:
            saved, payload_json = self._prepare(
                decision_case, DecisionCase, "decision case"
            )
            try:
                self._registry.connection.execute(
                    """
                    INSERT INTO shipyard_decision_cases(case_id, workspace_id, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (saved.case_id, saved.workspace_id, payload_json),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("decision case already exists") from exc
            return saved

        return self._write(insert)

    def get_decision_case(self, case_id: str) -> DecisionCase:
        def select() -> DecisionCase:
            row = self._registry.connection.execute(
                "SELECT * FROM shipyard_decision_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            if row is None:
                raise KeyError(case_id)
            return self._decision_case_from_row(row)

        return self._read(select)

    def list_decision_cases(self, workspace_id: str | None = None) -> list[DecisionCase]:
        def select() -> list[DecisionCase]:
            if workspace_id is None:
                rows = self._registry.connection.execute(
                    "SELECT * FROM shipyard_decision_cases ORDER BY case_id"
                ).fetchall()
            else:
                rows = self._registry.connection.execute(
                    """
                    SELECT * FROM shipyard_decision_cases
                    WHERE workspace_id = ?
                    ORDER BY case_id
                    """,
                    (workspace_id,),
                ).fetchall()
            return [self._decision_case_from_row(row) for row in rows]

        return self._read(select)

    def put_proposal(self, proposal: AgentProposal) -> AgentProposal:
        def insert() -> AgentProposal:
            saved, payload_json = self._prepare(proposal, AgentProposal, "proposal")
            try:
                self._registry.connection.execute(
                    """
                    INSERT INTO shipyard_proposals(
                        proposal_id, revision, workspace_id, payload_json, content_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        saved.proposal_id,
                        saved.revision,
                        saved.workspace_id,
                        payload_json,
                        saved.content_hash,
                        saved.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("proposal revision already exists") from exc
            return saved

        return self._write(insert)

    def get_proposal(self, proposal_id: str) -> AgentProposal:
        def select() -> AgentProposal:
            row = self._registry.connection.execute(
                """
                SELECT * FROM shipyard_proposals
                WHERE proposal_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            return self._proposal_from_row(row)

        return self._read(select)

    def list_proposals(self, workspace_id: str | None = None) -> list[AgentProposal]:
        def select() -> list[AgentProposal]:
            if workspace_id is None:
                rows = self._registry.connection.execute(
                    "SELECT * FROM shipyard_proposals ORDER BY proposal_id, revision"
                ).fetchall()
            else:
                rows = self._registry.connection.execute(
                    """
                    SELECT * FROM shipyard_proposals
                    WHERE workspace_id = ?
                    ORDER BY proposal_id, revision
                    """,
                    (workspace_id,),
                ).fetchall()
            return [self._proposal_from_row(row) for row in rows]

        return self._read(select)

    def put_gate_review(self, gate_review: GateReviewSnapshot) -> GateReviewSnapshot:
        def insert() -> GateReviewSnapshot:
            saved, payload_json = self._prepare(
                gate_review, GateReviewSnapshot, "gate review"
            )
            try:
                self._registry.connection.execute(
                    """
                    INSERT INTO shipyard_gate_reviews(
                        gate_run_id, revision, workspace_id, payload_json, content_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        saved.gate_run_id,
                        saved.revision,
                        saved.workspace_id,
                        payload_json,
                        saved.content_hash,
                        saved.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("gate review already exists") from exc
            return saved

        return self._write(insert)

    def list_gate_reviews(self, workspace_id: str | None = None) -> list[GateReviewSnapshot]:
        def select() -> list[GateReviewSnapshot]:
            if workspace_id is None:
                rows = self._registry.connection.execute(
                    "SELECT * FROM shipyard_gate_reviews ORDER BY created_at, rowid"
                ).fetchall()
            else:
                rows = self._registry.connection.execute(
                    """
                    SELECT * FROM shipyard_gate_reviews
                    WHERE workspace_id = ?
                    ORDER BY created_at, rowid
                    """,
                    (workspace_id,),
                ).fetchall()
            return [self._gate_review_from_row(row) for row in rows]

        return self._read(select)

    def put_release_candidate(self, candidate: ReleaseCandidate) -> ReleaseCandidate:
        def insert() -> ReleaseCandidate:
            saved, payload_json = self._prepare(
                candidate, ReleaseCandidate, "release candidate"
            )
            try:
                self._registry.connection.execute(
                    """
                    INSERT INTO shipyard_release_candidates(
                        candidate_id, revision, workspace_id, payload_json, content_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        saved.candidate_id,
                        saved.revision,
                        saved.workspace_id,
                        payload_json,
                        saved.content_hash,
                        saved.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("release candidate already exists") from exc
            return saved

        return self._write(insert)

    def get_release_candidate(self, candidate_id: str) -> ReleaseCandidate:
        def select() -> ReleaseCandidate:
            row = self._registry.connection.execute(
                "SELECT * FROM shipyard_release_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            return self._release_candidate_from_row(row)

        return self._read(select)

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        def insert() -> AuditEvent:
            saved, payload_json = self._prepare(event, AuditEvent, "audit event")
            try:
                self._registry.connection.execute(
                    """
                    INSERT INTO shipyard_audit_events(
                        event_id, workspace_id, event_type, actor, actor_kind, payload_json,
                        event_hash, created_at, predecessor_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        saved.event_id,
                        saved.workspace_id,
                        saved.event_type,
                        saved.actor,
                        saved.actor_kind,
                        payload_json,
                        saved.event_hash,
                        saved.created_at.isoformat(),
                        saved.predecessor_hash,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("audit event already exists") from exc
            return saved

        return self._write(insert)

    def list_audit_events(self, workspace_id: str | None = None) -> list[AuditEvent]:
        def select() -> list[AuditEvent]:
            if workspace_id is None:
                rows = self._registry.connection.execute(
                    "SELECT * FROM shipyard_audit_events ORDER BY created_at, rowid"
                ).fetchall()
            else:
                rows = self._registry.connection.execute(
                    """
                    SELECT * FROM shipyard_audit_events
                    WHERE workspace_id = ?
                    ORDER BY created_at, rowid
                    """,
                    (workspace_id,),
                ).fetchall()
            return [self._audit_event_from_row(row) for row in rows]

        return self._read(select)

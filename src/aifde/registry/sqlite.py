"""SQLite adapter for the append-only AI FDE registry."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterator, TypeVar

from aifde.domain.artifacts import Artifact, canonical_json_bytes
from aifde.domain.evidence import Evidence


_T = TypeVar("_T")


def _canonical_json_text(value: Any) -> str:
    """Serialize values with the same strict canonical rules as artifacts."""
    try:
        return canonical_json_bytes(value).decode("utf-8")
    except ValueError as exc:
        raise ValueError("registry JSON fields must contain finite JSON values") from exc


class SQLiteRegistry:
    """A single-database registry with immutable artifact and evidence records."""

    def __init__(self, database: str | Path) -> None:
        self._connection = sqlite3.connect(str(database), isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._closed = False
        self._initialize_schema()
        self.artifacts = _SQLiteArtifactRepository(self)
        self.evidence = _SQLiteEvidenceRepository(self)

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the connection for operational inspection and migrations."""
        return self._connection

    def close(self) -> None:
        """Close the underlying database connection; repeated calls are safe."""
        if not self._closed:
            if self._connection.in_transaction:
                self._connection.rollback()
            self._connection.close()
            self._closed = True

    def transaction(self) -> _SQLiteRegistryTransaction:
        """Begin an explicit transaction for atomic multi-repository writes."""
        self._ensure_open()
        if self._connection.in_transaction:
            raise RuntimeError("a registry transaction is already active")
        self._connection.execute("BEGIN IMMEDIATE")
        return _SQLiteRegistryTransaction(self)

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        self._ensure_open()
        if self._connection.in_transaction:
            yield
            return
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
                version INTEGER NOT NULL CHECK (version >= 1),
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                owner TEXT NOT NULL,
                content_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                depends_on_json TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
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
            """
        )


class _SQLiteRegistryTransaction:
    """Transaction handle that deliberately requires an explicit commit."""

    def __init__(self, registry: SQLiteRegistry) -> None:
        self._registry = registry
        self._complete = False
        self.artifacts = _SQLiteArtifactRepository(registry)
        self.evidence = _SQLiteEvidenceRepository(registry)

    def commit(self) -> None:
        """Commit once; a failed transaction must be discarded by the caller."""
        if self._complete:
            raise RuntimeError("registry transaction is already complete")
        if not self._registry.connection.in_transaction:
            raise RuntimeError("registry transaction is no longer active")
        self._registry.connection.commit()
        self._complete = True


class _SQLiteArtifactRepository:
    def __init__(self, registry: SQLiteRegistry) -> None:
        self._registry = registry

    def put(self, artifact: Artifact) -> Artifact:
        """Insert a new version and reject all attempts to replace a version."""
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

            latest = connection.execute(
                """
                SELECT MAX(version) AS version FROM artifact_versions
                WHERE project_id = ? AND artifact_id = ?
                """,
                (artifact.project_id, artifact.artifact_id),
            ).fetchone()["version"]
            if latest is not None and artifact.version <= latest:
                raise ValueError("artifact versions are immutable and append-only")

            try:
                connection.execute(
                    """
                    INSERT INTO artifact_versions(
                        project_id, artifact_id, version, kind, status, owner,
                        content_json, content_hash, depends_on_json, evidence_refs_json,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("artifact versions are immutable") from exc
            return artifact

        return self._registry._write(insert)

    def get(
        self, project_id: str, artifact_id: str, version: int | None = None
    ) -> Artifact:
        query = """
            SELECT * FROM artifact_versions
            WHERE project_id = ? AND artifact_id = ?
        """
        parameters: tuple[Any, ...] = (project_id, artifact_id)
        if version is None:
            query += " ORDER BY version DESC LIMIT 1"
        else:
            query += " AND version = ?"
            parameters += (version,)
        row = self._registry.connection.execute(query, parameters).fetchone()
        if row is None:
            raise KeyError((project_id, artifact_id, version))
        return self._artifact_from_row(row)

    def list_versions(self, project_id: str, artifact_id: str) -> list[Artifact]:
        rows = self._registry.connection.execute(
            """
            SELECT * FROM artifact_versions
            WHERE project_id = ? AND artifact_id = ?
            ORDER BY version ASC
            """,
            (project_id, artifact_id),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> Artifact:
        return Artifact.model_validate(
            {
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
            }
        )


class _SQLiteEvidenceRepository:
    def __init__(self, registry: SQLiteRegistry) -> None:
        self._registry = registry

    def put(self, evidence: Evidence, content: bytes) -> Evidence:
        """Insert evidence once, deriving its hash from the original bytes."""
        if not isinstance(content, bytes):
            raise TypeError("evidence content must be bytes")
        saved = evidence.model_copy(update={"content_hash": sha256(content).hexdigest()})

        def insert() -> Evidence:
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

"""Behavioral tests for the immutable SQLite registry."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from aifde.domain.artifacts import Artifact, canonical_json_bytes
from aifde.domain.evidence import Evidence
from aifde.registry.sqlite import SQLiteRegistry


@pytest.fixture
def registry(tmp_path: Path):
    instance = SQLiteRegistry(tmp_path / "registry.db")
    yield instance
    instance.close()


def make_artifact(*, version: str, content: dict[str, object]) -> Artifact:
    return Artifact.build(
        artifact_id="artifact-1",
        project_id="p1",
        kind="DecisionContract",
        version=version,
        owner="owner-1",
        content=content,
        metadata={"z": 1, "a": 2},
    )


def make_evidence() -> Evidence:
    fixture = Path(__file__).parents[1] / "fixtures" / "evidence.json"
    return Evidence.model_validate(json.loads(fixture.read_text(encoding="utf-8")))


def test_artifact_versions_are_append_only_and_persist(registry, tmp_path: Path):
    """Removing duplicate-version protection would overwrite immutable history."""
    first = make_artifact(version="0.1.0", content={"b": 1, "a": 2})
    second = make_artifact(version="0.2.0", content={"a": 3})
    registry.artifacts.put(first)
    registry.artifacts.put(second)

    versions = registry.artifacts.list_versions("p1", first.artifact_id)
    assert [item.version for item in versions] == ["0.1.0", "0.2.0"]
    assert registry.artifacts.get("p1", first.artifact_id).content == {"a": 3}
    assert registry.artifacts.get("p1", first.artifact_id, version="0.1.0").content == {
        "a": 2,
        "b": 1,
    }

    with pytest.raises(ValueError, match="immutable"):
        registry.artifacts.put(make_artifact(version="0.1.0", content={"a": "changed"}))

    registry.artifacts.put(make_artifact(version="0.10.0", content={"a": "newest"}))
    assert registry.artifacts.get("p1", first.artifact_id).version == "0.10.0"
    assert [item.version for item in registry.artifacts.list_versions("p1", first.artifact_id)] == [
        "0.1.0",
        "0.2.0",
        "0.10.0",
    ]
    with pytest.raises(ValueError, match="append-only"):
        registry.artifacts.put(make_artifact(version="0.2.1", content={"a": "late"}))

    registry.close()
    persisted = SQLiteRegistry(tmp_path / "registry.db")
    try:
        assert persisted.artifacts.get("p1", first.artifact_id, "0.1.0") == first
    finally:
        persisted.close()


def test_registry_get_explicitly_normalizes_legacy_integer_versions(registry):
    """Removing legacy normalization would break existing integer version lookups."""
    artifact = make_artifact(version="1.0.0", content={"a": 1})
    registry.artifacts.put(artifact)

    assert registry.artifacts.get("p1", artifact.artifact_id, 1) == artifact
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        registry.artifacts.get("p1", artifact.artifact_id, "1")


def test_artifact_json_is_stored_in_canonical_form(registry):
    """Removing canonical serialization would make equivalent content unstable on disk."""
    artifact = make_artifact(version="1.0.0", content={"z": [2, 1], "a": {"b": True}})
    registry.artifacts.put(artifact)

    row = registry.connection.execute(
        "SELECT content_json, metadata_json FROM artifact_versions "
        "WHERE project_id = ? AND artifact_id = ? AND version = ?",
        (artifact.project_id, artifact.artifact_id, artifact.version),
    ).fetchone()
    assert row["content_json"] == canonical_json_bytes(artifact.content).decode("utf-8")
    assert row["metadata_json"] == '{"a":2,"z":1}'


def test_evidence_content_hash_matches_stored_bytes(registry):
    """Removing byte hashing would let evidence metadata disagree with stored evidence."""
    payload = b"source evidence"
    saved = registry.evidence.put(make_evidence(), payload)

    assert saved.content_hash == sha256(payload).hexdigest()
    assert registry.evidence.get(saved.evidence_id) == saved
    assert registry.evidence.read_content(saved.evidence_id) == payload

    with pytest.raises(ValueError, match="immutable"):
        registry.evidence.put(make_evidence(), b"changed source evidence")


def test_explicit_transaction_commits_artifact_and_evidence(registry):
    """Removing explicit transaction commit would leave a partial registry write behind."""
    artifact = make_artifact(version="1.0.0", content={"a": 1})
    payload = b"transactional evidence"

    transaction = registry.transaction()
    transaction.artifacts.put(artifact)
    transaction.evidence.put(make_evidence(), payload)
    transaction.commit()

    assert registry.artifacts.get("p1", artifact.artifact_id) == artifact
    assert registry.evidence.read_content("evidence-1") == payload


def test_transaction_failure_rolls_back_prior_writes_and_rejects_commit(registry):
    """Removing abort-on-write-failure would commit writes made before the failure."""
    transaction = registry.transaction()
    artifact = make_artifact(version="1.0.0", content={"a": 1})
    transaction.artifacts.put(artifact)

    with pytest.raises(ValueError, match="immutable"):
        transaction.artifacts.put(make_artifact(version="1.0.0", content={"a": 2}))
    with pytest.raises(RuntimeError, match="aborted"):
        transaction.commit()
    with pytest.raises(KeyError):
        registry.artifacts.get("p1", artifact.artifact_id)


def test_transaction_rollback_and_close_discard_uncommitted_writes(registry, tmp_path: Path):
    """Removing unfinished-transaction cleanup would persist rolled-back writes."""
    rolled_back = make_artifact(version="1.0.0", content={"a": 1})
    transaction = registry.transaction()
    transaction.artifacts.put(rolled_back)
    transaction.rollback()
    with pytest.raises(KeyError):
        registry.artifacts.get("p1", rolled_back.artifact_id)

    uncommitted = Artifact.build(
        artifact_id="artifact-close",
        project_id="p1",
        kind="DecisionContract",
        version="1.0.0",
        owner="owner-1",
        content={"a": 2},
    )
    transaction = registry.transaction()
    transaction.artifacts.put(uncommitted)
    registry.close()

    reopened = SQLiteRegistry(tmp_path / "registry.db")
    try:
        with pytest.raises(KeyError):
            reopened.artifacts.get("p1", uncommitted.artifact_id)
    finally:
        reopened.close()

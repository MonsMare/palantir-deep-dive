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


def make_artifact(*, version: int, content: dict[str, object]) -> Artifact:
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
    first = make_artifact(version=1, content={"b": 1, "a": 2})
    second = make_artifact(version=2, content={"a": 3})
    registry.artifacts.put(first)
    registry.artifacts.put(second)

    versions = registry.artifacts.list_versions("p1", first.artifact_id)
    assert [item.version for item in versions] == [1, 2]
    assert registry.artifacts.get("p1", first.artifact_id).content == {"a": 3}
    assert registry.artifacts.get("p1", first.artifact_id, version=1).content == {
        "a": 2,
        "b": 1,
    }

    with pytest.raises(ValueError, match="immutable"):
        registry.artifacts.put(make_artifact(version=1, content={"a": "changed"}))

    registry.artifacts.put(make_artifact(version=3, content={"a": "newest"}))
    with pytest.raises(ValueError, match="append-only"):
        registry.artifacts.put(make_artifact(version=2, content={"a": "late"}))

    registry.close()
    persisted = SQLiteRegistry(tmp_path / "registry.db")
    try:
        assert persisted.artifacts.get("p1", first.artifact_id, 1) == first
    finally:
        persisted.close()


def test_artifact_json_is_stored_in_canonical_form(registry):
    """Removing canonical serialization would make equivalent content unstable on disk."""
    artifact = make_artifact(version=1, content={"z": [2, 1], "a": {"b": True}})
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
    artifact = make_artifact(version=1, content={"a": 1})
    payload = b"transactional evidence"

    transaction = registry.transaction()
    transaction.artifacts.put(artifact)
    transaction.evidence.put(make_evidence(), payload)
    transaction.commit()

    assert registry.artifacts.get("p1", artifact.artifact_id) == artifact
    assert registry.evidence.read_content("evidence-1") == payload

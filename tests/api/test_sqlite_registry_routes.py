"""Real SQLiteRegistry-backed cockpit integration tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aifde.api.app import create_app
from aifde.domain.artifacts import Artifact
from aifde.registry.sqlite import SQLiteRegistry


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def test_real_sqlite_registry_cockpit_reads_from_fastapi_request_thread(
    tmp_path,
) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    try:
        registry.artifacts.put(
            Artifact.build(
                artifact_id="decision-1",
                project_id="p1",
                kind="DecisionContract",
                version="0.10.0",
                owner="owner-1",
                content={"decision": "prioritize"},
            )
        )
        registry.connection.execute(
            "INSERT INTO stage_runs(stage_run_id, project_id, payload_json) VALUES (?, ?, ?)",
            (
                "run-1",
                "p1",
                json.dumps(
                    {
                        "stage_id": "decision.contract",
                        "state": "domain_review",
                        "blocking_gate_ids": [],
                        "pending_approval_ids": [],
                        "latest_run_id": "run-1",
                    }
                ),
            ),
        )
        registry.connection.execute(
            "INSERT INTO gate_runs(gate_run_id, project_id, payload_json) VALUES (?, ?, ?)",
            (
                "gate-run-1",
                "p1",
                json.dumps(
                    {
                        "gate_id": "semantic.integrity",
                        "severity": "hard",
                        "status": "passed",
                        "stage_id": "decision.contract",
                        "latest_run_id": "gate-run-1",
                    }
                ),
            ),
        )

        app = create_app(
            registry=registry,
            gate_engine=SimpleNamespace(),
            stage_runner=SimpleNamespace(),
            action_broker=SimpleNamespace(),
        )
        client = TestClient(app)

        artifacts = client.get("/projects/p1/artifacts")
        stages = client.get("/projects/p1/stages")
        gates = client.get("/projects/p1/gates")

        assert artifacts.status_code == 200
        assert artifacts.json()[0]["artifact_id"] == "decision-1"
        assert artifacts.json()[0]["version"] == "0.10.0"
        assert stages.status_code == 200
        assert stages.json()[0]["latest_run_id"] == "run-1"
        assert gates.status_code == 200
        assert gates.json()[0]["gate_id"] == "semantic.integrity"
        assert client.get("/projects/unknown/artifacts").status_code == 404
    finally:
        registry.close()

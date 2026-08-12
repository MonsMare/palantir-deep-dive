from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from aifde.domain.artifacts import Artifact
from aifde.domain.evidence import Claim
from aifde.domain.stages import StageState


def test_artifact_requires_identity_and_kind():
    with pytest.raises(ValidationError):
        Artifact(project_id="p1", kind="OntologyModel")


def test_artifact_hash_is_stable_for_same_content():
    first = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
    )
    second = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
    )
    assert first.content_hash == second.content_hash


def test_claim_rejects_unknown_claim_type():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1",
            artifact_id="a1",
            claim_type="guess",
            text="unsupported",
        )


def test_stage_state_has_blocked_state():
    assert StageState.BLOCKED.value == "blocked"

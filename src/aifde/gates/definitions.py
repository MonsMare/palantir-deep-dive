"""Built-in, versioned gate definitions."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from aifde.domain.artifacts import canonical_json_bytes


class GateDefinition(BaseModel):
    """Governance policy for one named validation gate."""

    model_config = ConfigDict(extra="allow", frozen=True)

    gate_id: str
    category: Literal[
        "reality",
        "evidence",
        "semantic",
        "data",
        "executable",
        "adversarial",
        "business",
        "release_governance",
    ]
    severity: Literal["hard", "soft"]
    version: str = "1.0.0"
    validator_version: str = "1.0.0"

    @field_validator("gate_id", "version", "validator_version")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @property
    def definition_fingerprint(self) -> str:
        """Hash every canonical policy field, including fields added in the future."""
        return sha256(
            canonical_json_bytes(self.model_dump(mode="json"))
        ).hexdigest()


BUILT_IN_GATE_DEFINITIONS: tuple[GateDefinition, ...] = (
    GateDefinition(gate_id="reality.consistency", category="reality", severity="hard"),
    GateDefinition(gate_id="evidence.coverage", category="evidence", severity="hard"),
    GateDefinition(gate_id="semantic.integrity", category="semantic", severity="hard"),
    GateDefinition(gate_id="data.quality", category="data", severity="hard"),
    GateDefinition(gate_id="executable.readiness", category="executable", severity="hard"),
    GateDefinition(gate_id="adversarial.challenge", category="adversarial", severity="hard"),
    GateDefinition(
        gate_id="business.exception_coverage", category="business", severity="soft"
    ),
    GateDefinition(
        gate_id="release.governance", category="release_governance", severity="hard"
    ),
)

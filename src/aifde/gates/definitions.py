"""Built-in, versioned gate definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class GateDefinition(BaseModel):
    """Governance policy for one named validation gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

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

"""Small CLI-facing adapters that preserve the platform transition authority."""

from __future__ import annotations

from aifde.domain.stages import StageState
from aifde.gates.engine import GateEngine, TransitionBlocked


def transition_stage_run(
    gate_engine: GateEngine,
    *,
    stage_run_id: str,
    target: StageState,
    actor: str,
):
    """Request a transition through the same Gate Engine used by API and Runner."""
    target = target if isinstance(target, StageState) else StageState(target)
    decision = gate_engine.can_transition(stage_run_id, target)
    if not decision.allowed:
        raise TransitionBlocked(f"transition blocked: {decision.reason}")
    return gate_engine.transition(stage_run_id, target, actor=actor)

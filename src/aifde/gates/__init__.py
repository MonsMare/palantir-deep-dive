"""Versioned quality gates and guarded stage transitions."""

from .engine import GateEngine, TransitionBlocked

__all__ = ["GateEngine", "TransitionBlocked"]

"""Memory Evolution layer (v0.4c).

Evolvers operate on existing memories — symmetric to Extractors which operate
on text. Every evolver returns an ``EvolutionResult`` whose ``records`` are
the audit trail of what was (or would be) done."""

from .base import EvolutionRecord, EvolutionResult, Evolver, annotate_history
from .contradictions import ContradictionSurfacer
from .drift import PreferenceDriftDetector
from .goals import GoalResolver, revert as revert_goal_resolution
from .summary import SummaryEvolver

__all__ = [
    "ContradictionSurfacer",
    "EvolutionRecord",
    "EvolutionResult",
    "Evolver",
    "GoalResolver",
    "PreferenceDriftDetector",
    "SummaryEvolver",
    "annotate_history",
    "revert_goal_resolution",
]

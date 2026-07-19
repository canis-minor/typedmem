"""Feature 5 — Simple reranking.

Combine three cheap signals into one score: semantic similarity (from vector
search), recency, and a type-match bonus (did the memory's type match the
router's predicted intent). No ML, no LLM — deterministic and benchmarkable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from ..schema import Memory
from .router import RetrievalIntent
from .vector_search import Candidate


@dataclass(frozen=True)
class RankWeights:
    semantic: float = 1.0
    recency: float = 0.3
    type_match: float = 0.5


@dataclass
class RankedMemory:
    memory: Memory
    score: float


def _recency_boost(m: Memory, now: datetime, half_life_days: float) -> float:
    age = (now - m.timestamp).total_seconds() / 86400.0
    if age <= 0:
        return 1.0
    return math.pow(0.5, age / max(half_life_days, 1e-9))


def rerank(
    candidates: list[Candidate],
    *,
    intent: RetrievalIntent | None = None,
    weights: RankWeights | None = None,
    now: datetime | None = None,
    recency_half_life_days: float = 30.0,
) -> list[RankedMemory]:
    """Score and sort candidates (descending). ``score = w.semantic * similarity
    + w.recency * recency_boost + w.type_match * (type in intent)``."""
    weights = weights or RankWeights()
    now = now or datetime.now(timezone.utc)
    preferred = set(intent.memory_types or []) if intent else set()
    ranked: list[RankedMemory] = []
    for c in candidates:
        m = c.memory
        rec = _recency_boost(m, now, recency_half_life_days)
        type_bonus = 1.0 if m.type in preferred else 0.0
        score = (
            weights.semantic * c.similarity
            + weights.recency * rec
            + weights.type_match * type_bonus
        )
        ranked.append(RankedMemory(m, score))
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked

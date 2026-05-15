"""GoalResolver: match active goals against evidence via semantic similarity.

Strict-by-default: threshold 0.85, evidence types limited to time-anchored
result-like types. ``previous_status`` is preserved on every resolution, so
``revert(store, goal_id)`` can undo a mistaken match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..embeddings import EmbeddingProvider, cosine
from .base import EvolutionRecord, EvolutionResult, annotate_history

if TYPE_CHECKING:
    from ..stores.base import MemoryStore


@dataclass
class _Match:
    memory_id: str
    score: float


class GoalResolver:
    name = "goal_resolver"

    def __init__(
        self,
        embedder: EmbeddingProvider,
        *,
        threshold: float = 0.85,
        evidence_types: tuple[str, ...] = ("event", "outcome", "finding"),
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        self.embedder = embedder
        self.threshold = threshold
        self.evidence_types = evidence_types

    def evolve(
        self,
        store: "MemoryStore",
        *,
        workspace: str | None = None,
        dry_run: bool = False,
    ) -> EvolutionResult:
        ws = workspace if workspace is not None else store.default_workspace

        # Active goals only (not superseded, status="active").
        goals = [
            m for m in store
            if m.workspace == ws and m.type == "goal"
            and m.superseded_by is None and (m.status is None or m.status == "active")
        ]
        candidates = [
            m for m in store
            if m.workspace == ws and m.type in self.evidence_types
            and m.superseded_by is None
        ]
        if not goals or not candidates:
            return EvolutionResult(self.name, [], dry_run)

        # Batch-embed everything once.
        goal_vecs = self.embedder.embed([g.content for g in goals])
        cand_vecs = self.embedder.embed([c.content for c in candidates])

        records: list[EvolutionRecord] = []
        for goal, gvec in zip(goals, goal_vecs):
            best = self._best_match(gvec, candidates, cand_vecs)
            if best is None or best.score < self.threshold:
                continue
            reason = f"semantic match to candidate at similarity {best.score:.3f}"
            record = EvolutionRecord(
                evolver=self.name,
                action="resolve",
                input_ids=[goal.id, best.memory_id],
                output_ids=[goal.id],
                reason=reason,
            )
            records.append(record)
            if not dry_run:
                goal.metadata["previous_status"] = goal.status or "active"
                goal.metadata["resolved_by"] = best.memory_id
                goal.metadata["resolved_score"] = best.score
                goal.status = "resolved"
                annotate_history(goal, record)
                goal.touch()
                store._put(goal)
        return EvolutionResult(self.name, records, dry_run)

    def _best_match(self, qvec, candidates, cand_vecs) -> _Match | None:
        best: _Match | None = None
        for cand, cvec in zip(candidates, cand_vecs):
            score = cosine(qvec, cvec)
            if best is None or score > best.score:
                best = _Match(memory_id=cand.id, score=score)
        return best


def revert(store: "MemoryStore", goal_id: str) -> bool:
    """Restore a goal to its ``previous_status`` (one level of undo).

    Returns True if a previous status was found and applied, False otherwise.
    Removes the ``previous_status`` / ``resolved_by`` / ``resolved_score``
    annotations on success."""
    m = store.get(goal_id)
    if m is None or m.type != "goal":
        return False
    prev = m.metadata.pop("previous_status", None)
    if prev is None:
        return False
    m.status = prev
    m.metadata.pop("resolved_by", None)
    m.metadata.pop("resolved_score", None)
    revert_record = EvolutionRecord(
        evolver="goal_resolver",
        action="revert",
        input_ids=[goal_id],
        output_ids=[goal_id],
        reason=f"restored status to {prev!r}",
    )
    annotate_history(m, revert_record)
    m.touch()
    store._put(m)
    return True

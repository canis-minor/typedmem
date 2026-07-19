"""GoalResolver: match active goals against evidence via semantic similarity.

Strict-by-default: threshold 0.85, evidence types limited to time-anchored
result-like types. ``previous_status`` is preserved on every resolution, so
``revert(store, goal_id)`` can undo a mistaken match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..embeddings import EmbeddingProvider, cosine
from ..kernel import Transition
from .base import EvolutionRecord, EvolutionResult

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
                # Build a fresh metadata value — never mutate the loaded goal's
                # dict before the transition succeeds (optimistic concurrency).
                updated_metadata = {
                    **goal.metadata,
                    "previous_status": goal.status or "active",
                    "resolved_by": best.memory_id,
                    "resolved_score": best.score,
                }
                store.apply_transition(
                    Transition(
                        action="resolve",
                        memory_id=goal.id,
                        expected_version=goal.version,
                        changes={"status": "resolved", "metadata": updated_metadata},
                        actor="evolver",
                        actor_name=self.name,
                        evidence=[best.memory_id],
                        reason=reason,
                    )
                )
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
    if "previous_status" not in m.metadata:
        return False
    prev = m.metadata["previous_status"]
    # Fresh metadata with the resolution annotations dropped — no in-place
    # mutation before the transition. Uses the goal's CURRENT version, so a
    # resolve→revert sequence is v1 → v2 → v3.
    updated_metadata = {
        k: v for k, v in m.metadata.items()
        if k not in ("previous_status", "resolved_by", "resolved_score")
    }
    store.apply_transition(
        Transition(
            action="revert",
            memory_id=goal_id,
            expected_version=m.version,
            changes={"status": prev, "metadata": updated_metadata},
            actor="evolver",
            actor_name="goal_resolver",
            reason=f"restored status to {prev!r}",
        )
    )
    return True

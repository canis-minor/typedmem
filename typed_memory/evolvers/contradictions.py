"""ContradictionSurfacer: walk the FLAG-generated contradiction graph.

Pure read — never mutates the store. Returns one EvolutionRecord per
connected component of two or more memories. ``dry_run`` is irrelevant
(reported as True) because this evolver has no side effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import EvolutionRecord, EvolutionResult

if TYPE_CHECKING:
    from ..stores.base import MemoryStore


def _collect_edges(memories) -> dict[str, set[str]]:
    """Return id → set of ids it conflicts with, restricted to memories
    actually present in the iterable (defensive against dangling references)."""
    by_id = {m.id: m for m in memories}
    edges: dict[str, set[str]] = {mid: set() for mid in by_id}
    for m in by_id.values():
        for other_id in m.metadata.get("conflicts_with", []):
            if other_id in by_id:
                edges[m.id].add(other_id)
                edges[other_id].add(m.id)
    return edges


def _connected_components(edges: dict[str, set[str]]) -> list[list[str]]:
    seen: set[str] = set()
    components: list[list[str]] = []
    for node in edges:
        if node in seen:
            continue
        # BFS from node
        stack = [node]
        component: list[str] = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            component.append(cur)
            stack.extend(edges[cur] - seen)
        if len(component) > 1:
            components.append(sorted(component))
    return components


class ContradictionSurfacer:
    name = "contradiction_surfacer"

    def evolve(
        self,
        store: "MemoryStore",
        *,
        workspace: str | None = None,
        dry_run: bool = False,
    ) -> EvolutionResult:
        ws = workspace if workspace is not None else store.default_workspace
        memories = [m for m in store if m.workspace == ws]
        edges = _collect_edges(memories)
        components = _connected_components(edges)
        records = [
            EvolutionRecord(
                evolver=self.name,
                action="flag",
                input_ids=list(component),
                reason=f"{len(component)} memories cross-link via conflicts_with",
            )
            for component in components
        ]
        # Always dry_run=True semantically — surfacer is read-only.
        return EvolutionResult(self.name, records, dry_run=True)

    def clusters(self, store: "MemoryStore", *, workspace: str | None = None):
        """Convenience: return clusters as lists of Memory objects."""
        result = self.evolve(store, workspace=workspace)
        by_id = {m.id: m for m in store}
        return [[by_id[i] for i in r.input_ids if i in by_id] for r in result.records]

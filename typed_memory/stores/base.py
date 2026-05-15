"""Abstract MemoryStore: concrete API on top of a few storage primitives.

v0.4a adds workspace scoping and ConflictPolicy dispatch. Subclasses still
only need to implement four primitives.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Iterator

from ..policy import ConflictAction, ConflictPolicy, PolicyEngine
from ..schema import Memory, MemoryType

if False:  # TYPE_CHECKING only; avoid hard import cycle
    from ..profiles.base import DomainProfile


class MemoryStore(ABC):
    """Subclasses implement the four primitives below; everything else is
    derived. Backends may override derived methods when SQL can answer faster.
    """

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        *,
        default_workspace: str = "default",
        profile: "DomainProfile | None" = None,
    ) -> None:
        self.policy = policy or PolicyEngine()
        self.default_workspace = default_workspace
        self.profile = profile

    # ── Primitives ────────────────────────────────────────────────────────
    @abstractmethod
    def _put(self, m: Memory) -> None: ...

    @abstractmethod
    def _get(self, memory_id: str) -> Memory | None: ...

    @abstractmethod
    def _delete(self, memory_id: str) -> bool: ...

    @abstractmethod
    def _iter(self) -> Iterator[Memory]: ...

    # ── Public API ────────────────────────────────────────────────────────
    def add(self, m: Memory) -> Memory:
        """Insert a memory, honoring the type's ConflictPolicy on slot collision.

        Slot key in v0.4a is (workspace, type, subject); subject-less memories
        never collide and are inserted directly. If a profile is bound, the
        memory is validated against it first (raises on failure — strict).
        """
        if self.profile is not None:
            errors = self.profile.validate(m)
            if errors:
                raise ValueError(
                    f"profile {self.profile.name!r} rejected memory: {errors}"
                )
        if m.subject is None:
            self._put(m)
            return m

        existing = self._find_same_slot(m.workspace, m.type, m.subject)
        if existing is None:
            self._put(m)
            return m

        action = self.policy.resolve(existing, m)
        return self._apply_conflict(existing, m, action)

    def add_many(self, ms: Iterable[Memory]) -> list[Memory]:
        return [self.add(m) for m in ms]

    def get(self, memory_id: str) -> Memory | None:
        return self._get(memory_id)

    def delete(self, memory_id: str) -> bool:
        return self._delete(memory_id)

    def all(self, *, workspace: str | None = None, include_superseded: bool = False) -> list[Memory]:
        ws = workspace if workspace is not None else self.default_workspace
        return [m for m in self._iter()
                if m.workspace == ws and (include_superseded or m.superseded_by is None)]

    def by_type(self, t: MemoryType, *, workspace: str | None = None,
                include_superseded: bool = False) -> list[Memory]:
        ws = workspace if workspace is not None else self.default_workspace
        return [m for m in self._iter()
                if m.type == t and m.workspace == ws
                and (include_superseded or m.superseded_by is None)]

    def workspaces(self) -> list[str]:
        return sorted({m.workspace for m in self._iter()})

    # ── Evolution helpers (v0.4c) ────────────────────────────────────────
    def contradictions(self, *, workspace: str | None = None) -> list[list[Memory]]:
        """Return groups of memories that cross-link via metadata.conflicts_with."""
        from ..evolvers.contradictions import ContradictionSurfacer
        return ContradictionSurfacer().clusters(self, workspace=workspace)

    def drift_flags(self, *, workspace: str | None = None) -> list[Memory]:
        """Memories that carry ``metadata['drift_flags']`` (post-drift-detector)."""
        ws = workspace if workspace is not None else self.default_workspace
        return [m for m in self._iter()
                if m.workspace == ws and m.metadata.get("drift_flags")]

    def evolution_history(self, memory_id: str) -> list[dict]:
        m = self._get(memory_id)
        if m is None:
            return []
        return list(m.metadata.get("evolution_history", []))

    def _find_same_slot(self, workspace: str, t: MemoryType, subject: str) -> Memory | None:
        for m in self._iter():
            if (m.type == t and m.subject == subject and m.workspace == workspace
                    and m.superseded_by is None):
                return m
        return None

    # ── Conflict dispatch ─────────────────────────────────────────────────
    def _apply_conflict(self, existing: Memory, incoming: Memory, action: ConflictAction) -> Memory:
        p = action.policy

        if p is ConflictPolicy.IGNORE:
            return existing

        if p is ConflictPolicy.KEEP_BOTH:
            self._put(incoming)
            return incoming

        if p is ConflictPolicy.REPLACE:
            existing.content = incoming.content
            existing.confidence = incoming.confidence
            existing.timestamp = incoming.timestamp
            existing.tags = list({*existing.tags, *incoming.tags})
            if incoming.sources:
                existing.sources = list(incoming.sources)
            existing.metadata = {**existing.metadata, **incoming.metadata}
            # Bookkeeping for PreferenceDriftDetector (v0.4c).
            from datetime import datetime, timezone
            log = existing.metadata.setdefault("replace_log", [])
            log.append(datetime.now(timezone.utc).isoformat())
            if len(log) > 20:
                del log[:-20]
            existing.metadata["replace_count"] = existing.metadata.get("replace_count", 0) + 1
            existing.touch()
            self._put(existing)
            return existing

        if p is ConflictPolicy.SUPERSEDE:
            existing.superseded_by = incoming.id
            existing.touch()
            self._put(existing)
            self._put(incoming)
            return incoming

        if p is ConflictPolicy.REINFORCE:
            seen = {s.key() for s in existing.sources}
            new_unique = [s for s in incoming.sources if s.key() not in seen]
            existing.sources.extend(new_unique)
            existing.confidence = self.policy.reinforce_confidence(
                existing.confidence, incoming.confidence, new_unique or incoming.sources,
            )
            # Tags accumulate; content prefers the higher-confidence version.
            existing.tags = list({*existing.tags, *incoming.tags})
            if incoming.confidence > existing.confidence:
                existing.content = incoming.content
            existing.touch()
            self._put(existing)
            return existing

        if p is ConflictPolicy.FLAG:
            existing.metadata.setdefault("conflicts_with", []).append(incoming.id)
            incoming.metadata.setdefault("conflicts_with", []).append(existing.id)
            existing.touch()
            self._put(existing)
            self._put(incoming)
            return incoming

        raise ValueError(f"unhandled ConflictPolicy: {p}")

    def __iter__(self) -> Iterator[Memory]:
        return self._iter()

    def __len__(self) -> int:
        return sum(1 for _ in self._iter())

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

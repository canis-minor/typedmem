"""Abstract MemoryStore: concrete API on top of a few storage primitives.

v0.6a adds a first-class memory event log. Every successful add/update/delete
emits a typed ``MemoryEvent``; subclasses implement two extra primitives
(``_append_event``, ``_iter_events``) on top of the four they already had.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Iterator

from ..events import EVENT_SOURCES, EventSource, MemoryEvent
from ..policy import ConflictAction, ConflictPolicy, PolicyEngine
from ..schema import Memory, MemoryType

if False:  # TYPE_CHECKING only; avoid hard import cycle
    from ..profiles.base import DomainProfile


def _record_lifecycle_event(
    store: "MemoryStore",
    m: Memory,
    *,
    action: str,
    input_ids: list[str],
    output_ids: list[str],
    reason: str,
    source: EventSource = "store",
    source_name: str | None = None,
) -> None:
    """Emit a MemoryEvent for a lifecycle change. Replaces the v0.4.2
    ``metadata["evolution_history"]`` write — the event log is now indexed
    storage with no 50-entry cap, and ``evolution_history(memory_id)`` reads
    back through this same log."""
    event = MemoryEvent(
        memory_id=m.id,
        workspace=m.workspace,
        type=m.type,
        subject=m.subject,
        action=action,
        source=source,
        source_name=source_name,
        reason=reason,
        input_ids=list(input_ids),
        output_ids=list(output_ids),
    )
    store._append_event(event)


class MemoryStore(ABC):
    """Subclasses implement six primitives below; everything else is derived.
    Backends may override derived methods when SQL can answer faster.
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
        # Lazily-migrated memory ids — keys whose legacy
        # ``metadata["evolution_history"]`` has been folded into the event
        # log. We only migrate once per memory per process.
        self._migrated_ids: set[str] = set()

    # ── Primitives ────────────────────────────────────────────────────────
    @abstractmethod
    def _put(self, m: Memory) -> None: ...

    @abstractmethod
    def _get(self, memory_id: str) -> Memory | None: ...

    @abstractmethod
    def _delete(self, memory_id: str) -> bool: ...

    @abstractmethod
    def _iter(self) -> Iterator[Memory]: ...

    @abstractmethod
    def _append_event(self, event: MemoryEvent) -> None: ...

    @abstractmethod
    def _iter_events(self) -> Iterator[MemoryEvent]: ...

    # ── Public API ────────────────────────────────────────────────────────
    def add(
        self,
        m: Memory,
        *,
        event_source: EventSource = "store",
        event_source_name: str | None = None,
    ) -> Memory:
        """Insert a memory, honoring the type's ConflictPolicy on slot collision.

        Slot key is (workspace, type, subject); subject-less memories never
        collide and are inserted directly. If a profile is bound, the memory
        is validated first (raises on failure — strict).

        ``event_source``/``event_source_name`` tag the resulting MemoryEvent
        so consumers can tell "agent wrote this" from "evolver promoted this"
        from "migration imported this". Defaults are ``"store"`` / ``None``,
        which preserves all v0.5 call sites.
        """
        if event_source not in EVENT_SOURCES:
            raise ValueError(
                f"event_source must be one of {sorted(EVENT_SOURCES)}, "
                f"got {event_source!r}"
            )
        if self.profile is not None:
            errors = self.profile.validate(m)
            if errors:
                raise ValueError(
                    f"profile {self.profile.name!r} rejected memory: {errors}"
                )
        if m.subject is None:
            self._put(m)
            _record_lifecycle_event(
                self, m, action="added",
                input_ids=[m.id], output_ids=[m.id], reason="",
                source=event_source, source_name=event_source_name,
            )
            return m

        existing = self._find_same_slot(m.workspace, m.type, m.subject)
        if existing is None:
            self._put(m)
            _record_lifecycle_event(
                self, m, action="added",
                input_ids=[m.id], output_ids=[m.id], reason="",
                source=event_source, source_name=event_source_name,
            )
            return m

        action = self.policy.resolve(existing, m)
        return self._apply_conflict(
            existing, m, action,
            event_source=event_source, event_source_name=event_source_name,
        )

    def add_many(
        self,
        ms: Iterable[Memory],
        *,
        event_source: EventSource = "store",
        event_source_name: str | None = None,
    ) -> list[Memory]:
        return [
            self.add(m, event_source=event_source, event_source_name=event_source_name)
            for m in ms
        ]

    def get(self, memory_id: str) -> Memory | None:
        return self._get(memory_id)

    def delete(
        self,
        memory_id: str,
        *,
        event_source: EventSource = "store",
        event_source_name: str | None = None,
    ) -> bool:
        """Delete a memory. Emits a ``deleted`` MemoryEvent BEFORE the row is
        removed, so the event survives in the log and ``changed_since()``
        surfaces deletions to consumers staying in sync."""
        if event_source not in EVENT_SOURCES:
            raise ValueError(
                f"event_source must be one of {sorted(EVENT_SOURCES)}, "
                f"got {event_source!r}"
            )
        existing = self._get(memory_id)
        if existing is None:
            return False
        _record_lifecycle_event(
            self, existing, action="deleted",
            input_ids=[memory_id], output_ids=[], reason="",
            source=event_source, source_name=event_source_name,
        )
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

    # ── Timeline (v0.6a) ─────────────────────────────────────────────────
    def history(self, memory_id: str) -> list[MemoryEvent]:
        """Every event that touched this memory, oldest first. Includes the
        ``deleted`` event even after the memory row is gone."""
        self._migrate_legacy_history(memory_id)
        events = [e for e in self._iter_events() if e.memory_id == memory_id]
        events.sort(key=lambda e: e.timestamp)
        return events

    def timeline(
        self,
        *,
        subject: str | None = None,
        type: str | None = None,
        workspace: str | None = None,
        source: EventSource | None = None,
    ) -> list[MemoryEvent]:
        """Filtered event stream, oldest first. All filters are AND-combined;
        omitted filters match anything. Workspace defaults to None (all
        workspaces) so callers can audit globally."""
        type_str = type.value if isinstance(type, MemoryType) else type
        if source is not None and source not in EVENT_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(EVENT_SOURCES)}, got {source!r}"
            )
        self._migrate_legacy_history_all()
        out: list[MemoryEvent] = []
        for e in self._iter_events():
            if subject is not None and e.subject != subject:
                continue
            if type_str is not None and e.type != type_str:
                continue
            if workspace is not None and e.workspace != workspace:
                continue
            if source is not None and e.source != source:
                continue
            out.append(e)
        out.sort(key=lambda e: e.timestamp)
        return out

    def changed_since(self, timestamp: datetime) -> list[MemoryEvent]:
        """All events strictly after ``timestamp``, oldest first. The canonical
        change feed for consumers staying in sync — includes adds, updates,
        deletes, and evolver-driven transforms."""
        self._migrate_legacy_history_all()
        out = [e for e in self._iter_events() if e.timestamp > timestamp]
        out.sort(key=lambda e: e.timestamp)
        return out

    # ── Legacy compat ────────────────────────────────────────────────────
    def evolution_history(self, memory_id: str) -> list[dict]:
        """v0.4.2-compatible shape: list of dicts with ``evolver``, ``action``,
        ``input_ids``, ``output_ids``, ``reason``, ``timestamp``. Backed by
        the v0.6a event log; entries that were stored in
        ``metadata["evolution_history"]`` migrate on first access."""
        return [e.to_legacy_history_dict() for e in self.history(memory_id)]

    # ── Evolution helpers ────────────────────────────────────────────────
    def contradictions(self, *, workspace: str | None = None) -> list[list[Memory]]:
        """Return groups of memories that cross-link via metadata.conflicts_with."""
        from ..evolvers.contradictions import ContradictionSurfacer
        return ContradictionSurfacer().clusters(self, workspace=workspace)

    def drift_flags(self, *, workspace: str | None = None) -> list[Memory]:
        """Memories that carry ``metadata['drift_flags']`` (post-drift-detector)."""
        ws = workspace if workspace is not None else self.default_workspace
        return [m for m in self._iter()
                if m.workspace == ws and m.metadata.get("drift_flags")]

    def _find_same_slot(self, workspace: str, t: MemoryType, subject: str) -> Memory | None:
        for m in self._iter():
            if (m.type == t and m.subject == subject and m.workspace == workspace
                    and m.superseded_by is None):
                return m
        return None

    # ── Lazy migration of metadata["evolution_history"] ─────────────────
    def _migrate_legacy_history(self, memory_id: str) -> None:
        if memory_id in self._migrated_ids:
            return
        m = self._get(memory_id)
        if m is None:
            self._migrated_ids.add(memory_id)
            return
        legacy = m.metadata.get("evolution_history")
        if not legacy:
            self._migrated_ids.add(memory_id)
            return
        for entry in legacy:
            ts = entry.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts_dt = datetime.fromisoformat(ts)
                except ValueError:
                    ts_dt = None
            else:
                ts_dt = None
            event = MemoryEvent(
                memory_id=memory_id,
                workspace=m.workspace,
                type=m.type,
                subject=m.subject,
                action=str(entry.get("action", "annotated")),
                source="system",
                source_name="migrate_evolution_history",
                reason=str(entry.get("reason", "")),
                input_ids=list(entry.get("input_ids", [])),
                output_ids=list(entry.get("output_ids", [])),
                payload={"legacy_evolver": entry.get("evolver")},
                timestamp=ts_dt or MemoryEvent.__dataclass_fields__["timestamp"].default_factory(),
            )
            self._append_event(event)
        m.metadata.pop("evolution_history", None)
        self._put(m)
        self._migrated_ids.add(memory_id)

    def _migrate_legacy_history_all(self) -> None:
        """Walk every memory once and migrate any leftover legacy history.
        Per-memory work is gated by ``_migrated_ids`` so this is O(n) only on
        the first call and cheap thereafter."""
        for m in list(self._iter()):
            if m.id in self._migrated_ids:
                continue
            self._migrate_legacy_history(m.id)

    # ── Conflict dispatch ─────────────────────────────────────────────────
    def _apply_conflict(
        self,
        existing: Memory,
        incoming: Memory,
        action: ConflictAction,
        *,
        event_source: EventSource = "store",
        event_source_name: str | None = None,
    ) -> Memory:
        p = action.policy

        if p is ConflictPolicy.IGNORE:
            return existing

        if p is ConflictPolicy.KEEP_BOTH:
            self._put(incoming)
            _record_lifecycle_event(
                self, incoming, action="added",
                input_ids=[incoming.id], output_ids=[incoming.id],
                reason="kept-both alongside existing",
                source=event_source, source_name=event_source_name,
            )
            return incoming

        if p is ConflictPolicy.REPLACE:
            old_content = existing.content
            existing.content = incoming.content
            existing.confidence = incoming.confidence
            existing.timestamp = incoming.timestamp
            existing.tags = list({*existing.tags, *incoming.tags})
            if incoming.sources:
                existing.sources = list(incoming.sources)
            existing.metadata = {**existing.metadata, **incoming.metadata}
            from datetime import datetime, timezone
            log = existing.metadata.setdefault("replace_log", [])
            log.append(datetime.now(timezone.utc).isoformat())
            if len(log) > 20:
                del log[:-20]
            existing.metadata["replace_count"] = existing.metadata.get("replace_count", 0) + 1
            _record_lifecycle_event(
                self, existing, action="replaced",
                input_ids=[existing.id], output_ids=[existing.id],
                reason=f"content updated (was: {old_content[:60]!r})",
                source=event_source, source_name=event_source_name,
            )
            existing.touch()
            self._put(existing)
            return existing

        if p is ConflictPolicy.SUPERSEDE:
            existing.superseded_by = incoming.id
            _record_lifecycle_event(
                self, existing, action="superseded",
                input_ids=[existing.id], output_ids=[incoming.id],
                reason=f"superseded by new {incoming.type}",
                source=event_source, source_name=event_source_name,
            )
            _record_lifecycle_event(
                self, incoming, action="supersedes",
                input_ids=[existing.id, incoming.id], output_ids=[incoming.id],
                reason=f"supersedes earlier {existing.type}: {existing.content[:60]!r}",
                source=event_source, source_name=event_source_name,
            )
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
            existing.tags = list({*existing.tags, *incoming.tags})
            if incoming.confidence > existing.confidence:
                existing.content = incoming.content
            if new_unique:
                src_ids = ", ".join(s.document_id for s in new_unique)
                _record_lifecycle_event(
                    self, existing, action="reinforced",
                    input_ids=[existing.id], output_ids=[existing.id],
                    reason=f"+{len(new_unique)} source(s): {src_ids}",
                    source=event_source, source_name=event_source_name,
                )
            existing.touch()
            self._put(existing)
            return existing

        if p is ConflictPolicy.FLAG:
            existing.metadata.setdefault("conflicts_with", []).append(incoming.id)
            incoming.metadata.setdefault("conflicts_with", []).append(existing.id)
            _record_lifecycle_event(
                self, existing, action="flagged",
                input_ids=[existing.id, incoming.id], output_ids=[existing.id],
                reason=f"cross-linked to new {incoming.type}: {incoming.content[:60]!r}",
                source=event_source, source_name=event_source_name,
            )
            _record_lifecycle_event(
                self, incoming, action="flagged",
                input_ids=[existing.id, incoming.id], output_ids=[incoming.id],
                reason=f"cross-linked to existing {existing.type}: {existing.content[:60]!r}",
                source=event_source, source_name=event_source_name,
            )
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

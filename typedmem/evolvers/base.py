"""Evolver protocol and audit primitives.

An ``Evolver`` reads (and optionally mutates) a store, producing a list of
``EvolutionRecord``s that explain every action taken. This audit trail is the
load-bearing piece of the evolver contract — without it, an Evolver is a
black box that silently rewrites state, which destroys trust.

v0.6a: every mutating evolver emits a typed ``MemoryEvent`` through the
store's event log via ``annotate_history(store, memory, record)``.
The pre-v0.6 behavior of appending to ``memory.metadata["evolution_history"]``
is gone — the event log is the canonical change feed, the 50-entry cap is
gone with it, and ``store.evolution_history(memory_id)`` reads the same log
back in the legacy shape for backward compatibility.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..stores.base import MemoryStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class EvolutionRecord:
    evolver: str
    action: str                                  # flag|annotate|create|resolve|supersede
    input_ids: list[str]                         # memories that triggered the action
    output_ids: list[str] = field(default_factory=list)
    reason: str = ""
    timestamp: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class EvolutionResult:
    evolver: str
    records: list[EvolutionRecord]
    dry_run: bool

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self) -> Iterator[EvolutionRecord]:
        return iter(self.records)

    def summary(self) -> str:
        prefix = "[dry-run] " if self.dry_run else ""
        if not self.records:
            return f"{prefix}{self.evolver}: 0 actions"
        return f"{prefix}{self.evolver}: " + ", ".join(
            f"{r.action}({len(r.input_ids)}→{len(r.output_ids)})"
            for r in self.records
        )


class Evolver(Protocol):
    name: str
    def evolve(
        self,
        store: "MemoryStore",
        *,
        workspace: str | None = None,
        dry_run: bool = False,
    ) -> EvolutionResult: ...


def annotate_history(store: "MemoryStore", memory, record: EvolutionRecord) -> None:
    """Emit a MemoryEvent for an evolver-driven change. ``record.evolver``
    becomes ``source_name`` on the event; ``source`` is ``"evolver"``.

    Signature changed in v0.6a: takes the store as the first arg. Pre-v0.6
    callers passing ``(memory, record)`` will see a TypeError — update to
    the new signature. The metadata write is gone; the event log is the
    canonical audit trail."""
    from ..events import MemoryEvent
    event = MemoryEvent(
        memory_id=memory.id,
        workspace=memory.workspace,
        type=memory.type,
        subject=memory.subject,
        action=record.action,
        source="evolver",
        source_name=record.evolver,
        reason=record.reason,
        input_ids=list(record.input_ids),
        output_ids=list(record.output_ids),
        timestamp=record.timestamp,
    )
    store._append_event(event)

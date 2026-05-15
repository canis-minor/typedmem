"""Evolver protocol and audit primitives.

An ``Evolver`` reads (and optionally mutates) a store, producing a list of
``EvolutionRecord``s that explain every action taken. This audit trail is the
load-bearing piece of v0.4c — without it, an Evolver is a black box that
silently rewrites state, which destroys trust. Every mutating evolver also
appends the same record to ``memory.metadata["evolution_history"]`` so the
provenance travels with the data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..stores.base import MemoryStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Cap on metadata["evolution_history"] length. Oldest entries are dropped past
# this. Users who need full history will use v0.5's dedicated log table.
_HISTORY_CAP = 50


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


def annotate_history(memory, record: EvolutionRecord) -> None:
    """Append an EvolutionRecord to a memory's metadata audit trail.
    Capped at _HISTORY_CAP entries — oldest are dropped past that."""
    history = memory.metadata.setdefault("evolution_history", [])
    history.append(record.to_dict())
    if len(history) > _HISTORY_CAP:
        del history[:-_HISTORY_CAP]

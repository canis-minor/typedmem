"""Memory schema: typed memory objects and their classifications."""

from __future__ import annotations

import uuid
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .source import Source


class MemoryType(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    GOAL = "goal"
    EVENT = "event"
    OBSERVATION = "observation"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Memory:
    # ``type`` is a string for profile extensibility. The built-in
    # ``MemoryType`` enum remains importable and equality-comparable
    # (``MemoryType.FACT == "fact"``) but is no longer the storage type.
    type: str
    content: str
    confidence: float = 1.0
    timestamp: datetime = field(default_factory=_now)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject: str | None = None
    tags: list[str] = field(default_factory=list)

    # v0.4a additions ─────────────────────────────────────────────────────
    workspace: str = "default"
    sources: list[Source] = field(default_factory=list)
    superseded_by: str | None = None
    # ──────────────────────────────────────────────────────────────────────

    # DEPRECATED: kept only so v0.3 callers (Memory(..., source="rule")) keep
    # working. ``__post_init__`` lifts it into ``sources`` and clears it; it is
    # omitted from ``to_dict``. Slated for removal in v0.5.
    source: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=_now)
    status: str | None = None  # goal-specific today; profile-defined statuses later

    def __post_init__(self) -> None:
        # Accept MemoryType enum or any string; canonicalize to string.
        if isinstance(self.type, MemoryType):
            self.type = self.type.value
        if not isinstance(self.type, str) or not self.type:
            raise ValueError(f"Memory.type must be a non-empty string, got {self.type!r}")
        if isinstance(self.status, GoalStatus):
            self.status = self.status.value
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if self.type == MemoryType.GOAL and self.status is None:
            self.status = GoalStatus.ACTIVE.value

        # Lift legacy ``source`` (str) into ``sources`` list and clear it so
        # there is one canonical place for provenance.
        if self.source:
            warnings.warn(
                "Memory(source=...) is deprecated; pass sources=[Source(...)] instead.",
                DeprecationWarning, stacklevel=3,
            )
            lifted = Source.from_any(self.source)
            if lifted is not None and not any(s.document_id == lifted.document_id for s in self.sources):
                self.sources.append(lifted)
            self.source = None

    @property
    def primary_source(self) -> Source | None:
        return self.sources[0] if self.sources else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type                       # already a string
        d["timestamp"] = self.timestamp.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        d["sources"] = [s.to_dict() for s in self.sources]
        d.pop("source", None)  # deprecated field is not part of the canonical shape
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Memory":
        data = dict(d)
        # type & status are stored as strings; pass through as-is.
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        data.setdefault("workspace", "default")

        # Provenance lifting: prefer ``sources`` if present, else lift legacy
        # ``source`` string. ``source`` never makes it onto the constructed
        # Memory — it is consumed here.
        raw_sources = data.get("sources")
        legacy_source = data.pop("source", None)
        if raw_sources:
            data["sources"] = [Source.from_any(s) for s in raw_sources if s is not None]
            data["sources"] = [s for s in data["sources"] if s is not None]
        elif legacy_source:
            lifted = Source.from_any(legacy_source)
            data["sources"] = [lifted] if lifted is not None else []
        else:
            data["sources"] = []

        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def touch(self) -> None:
        self.updated_at = _now()

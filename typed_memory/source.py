"""Structured provenance for a Memory.

Every memory worth keeping in a domain agent comes from somewhere — a document,
a chunk, a paragraph, an API response. ``Source`` makes that origin first-class
so retrieval can cite, reinforcement can dedupe, and conflict handling can
trust authoritative sources over weak ones.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Source:
    document_id: str
    chunk_id: str | None = None
    span: tuple[int, int] | None = None
    retrieved_at: datetime = field(default_factory=_now)
    authority: float = 1.0
    uri: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id:
            raise ValueError("Source.document_id must be a non-empty string")
        if self.authority < 0:
            raise ValueError(f"Source.authority must be >= 0, got {self.authority}")
        if self.span is not None:
            if (not isinstance(self.span, tuple) or len(self.span) != 2
                    or not all(isinstance(x, int) for x in self.span)):
                raise ValueError(f"Source.span must be (int, int) or None, got {self.span!r}")

    # ── dedupe key for REINFORCE -------------------------------------------
    def key(self) -> tuple[str, str | None, tuple[int, int] | None]:
        """Hashable identity of *which slice of which document* this points to.

        Two chunks from the same document independently corroborating a fact
        count as distinct evidence — that's why ``chunk_id`` and ``span`` are
        part of the key, not just ``document_id``.
        """
        return (self.document_id, self.chunk_id, self.span)

    # ── serialization ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        if self.span is not None:
            d["span"] = list(self.span)  # JSON has no tuple
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Source":
        data = dict(d)
        if isinstance(data.get("retrieved_at"), str):
            data["retrieved_at"] = datetime.fromisoformat(data["retrieved_at"])
        if isinstance(data.get("span"), list) and len(data["span"]) == 2:
            data["span"] = tuple(data["span"])
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})

    # ── lifting ------------------------------------------------------------
    @classmethod
    def from_any(cls, value: "Source | dict[str, Any] | str | None") -> "Source | None":
        """Coerce arbitrary input into a Source. The migration hinge.

        Accepts:
          - Source       → passthrough
          - dict         → from_dict
          - str          → Source(document_id=str)
          - None         → None
        """
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            if not value:
                return None
            return cls(document_id=value)
        if isinstance(value, dict):
            return cls.from_dict(value)
        raise TypeError(f"cannot coerce {type(value).__name__} into Source")

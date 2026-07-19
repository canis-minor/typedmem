"""Feature 4 — Temporal resolution.

The first TypedMem-specific reasoning step: drop memories that are no longer
valid. Two rules, both simple by design:

1. ``remove_superseded`` — drop any memory with an explicit ``superseded_by``
   link (the store sets this under SUPERSEDE / REPLACE-style policies).
2. ``latest_per_slot`` — for *single-valued* types (preference, goal, decision,
   …), collapse the same ``(workspace, type, subject)`` slot to the newest
   memory. Multi-valued types (facts, events) pass through untouched, so we
   never drop legitimately-distinct facts.

No temporal-reasoning engine; ``as_of`` is a plain ``timestamp <= as_of`` cut.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ..schema import Memory


def remove_superseded(memories: Iterable[Memory]) -> list[Memory]:
    """Drop memories that have been explicitly superseded."""
    return [m for m in memories if m.superseded_by is None]


def latest_per_slot(memories: Iterable[Memory], *, types: set[str] | None = None) -> list[Memory]:
    """Collapse same-slot memories to the newest, but only for ``types``
    (single-valued). Memories of other types — or with no subject — pass through
    unchanged. Order of pass-through memories is preserved; collapsed winners are
    appended."""
    memories = list(memories)
    if not types:
        return memories
    collapse = set(types)
    best: dict[tuple[str, str, str | None], Memory] = {}
    passthrough: list[Memory] = []
    for m in memories:
        if m.type not in collapse or m.subject is None:
            passthrough.append(m)
            continue
        key = (m.workspace, m.type, m.subject)
        cur = best.get(key)
        if cur is None or m.timestamp > cur.timestamp:
            best[key] = m
    return passthrough + list(best.values())


def resolve_temporal(
    memories: Iterable[Memory],
    *,
    as_of: datetime | None = None,
    collapse_types: set[str] | None = None,
) -> list[Memory]:
    """Full temporal pass: remove superseded, apply an ``as_of`` cut, then
    collapse single-valued slots to their latest surviving member."""
    out = remove_superseded(memories)
    if as_of is not None:
        out = [m for m in out if m.timestamp <= as_of]
    return latest_per_slot(out, types=collapse_types)

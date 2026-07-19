"""Feature 2 — Typed metadata filtering.

Narrow the candidate set with cheap, exact predicates *before* semantic search:
memory type, entity (mapped to ``Memory.subject``), status, and point-in-time
(``as_of`` against ``Memory.timestamp``). Explicit call-site args override the
router's predicted intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..schema import Memory
from .router import RetrievalIntent


def _norm_types(types: list[str] | None) -> list[str] | None:
    if not types:
        return None
    return [t.value if isinstance(t, Enum) else t for t in types]


@dataclass
class RetrievalFilters:
    """Exact-match predicates applied before vector search. A ``None`` field is
    unconstrained. ``entity_ids`` matches ``Memory.subject``; ``as_of`` keeps
    memories with ``timestamp <= as_of``."""

    memory_types: list[str] | None = None
    entity_ids: list[str] | None = None
    status: str | None = None
    as_of: datetime | None = None
    workspace: str | None = None

    def matches(self, m: Memory) -> bool:
        if self.workspace is not None and m.workspace != self.workspace:
            return False
        if self.memory_types and m.type not in self.memory_types:
            return False
        if self.entity_ids and m.subject not in self.entity_ids:
            return False
        if self.status is not None and m.status != self.status:
            return False
        if self.as_of is not None and m.timestamp > self.as_of:
            return False
        return True


def build_filters(
    intent: RetrievalIntent | None = None,
    *,
    memory_types: list[str] | None = None,
    entity_ids: list[str] | None = None,
    status: str | None = None,
    as_of: datetime | None = None,
    workspace: str | None = None,
) -> RetrievalFilters:
    """Merge explicit args with the router's intent (explicit wins)."""
    types = memory_types if memory_types is not None else (intent.memory_types if intent else None)
    entities = entity_ids if entity_ids is not None else (intent.entity_ids if intent else None)
    return RetrievalFilters(
        memory_types=_norm_types(types),
        entity_ids=entities,
        status=status,
        as_of=as_of,
        workspace=workspace,
    )


def apply_filters(memories: list[Memory], filters: RetrievalFilters) -> list[Memory]:
    return [m for m in memories if filters.matches(m)]

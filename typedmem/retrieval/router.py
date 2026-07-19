"""Feature 1 — Typed query routing.

Predict which memory *types* a query is asking about, so downstream stages can
filter before semantic search. v0 is deliberately rule-based (keyword → type);
an LLM router can drop in behind the same ``route_query`` signature later.

Types are matched as strings against ``Memory.type`` (the built-ins are
``fact`` / ``preference`` / ``goal`` / ``event`` / ``observation``; profiles may
add more, e.g. ``decision`` / ``project``). Unknown keywords route to no type,
which means "search everything".
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetrievalIntent:
    """What the router predicts a query is after. Empty/None fields mean
    "no constraint" (search everything)."""

    memory_types: list[str] | None = None
    entity_ids: list[str] | None = None


# (keywords, memory_type) — first-match-wins order, but all matches accumulate.
# Keep this small and legible; it is a benchmark baseline, not an NLU system.
DEFAULT_ROUTES: list[tuple[tuple[str, ...], str]] = [
    (("prefer", "preference", "like", "favorite", "favourite", "enjoy", "favou"), "preference"),
    (("decide", "decision", "chose", "choose", "why did", "opted", "picked"), "decision"),
    (("goal", "working on", "trying to", "aim", "objective", "project", "plan to"), "goal"),
    (("happen", "event", "did i", "occurred", "when did", "last time"), "event"),
    (("observe", "noticed", "observation", "seems"), "observation"),
    (("fact", "who is", "what is", "where is", "how many"), "fact"),
]


def route_query(query: str, *, routes: list[tuple[tuple[str, ...], str]] | None = None) -> RetrievalIntent:
    """Rule-based intent classification. Returns the predicted memory types in
    route order (deduped). ``entity_ids`` is left to the caller in v0 — entity
    linking is out of scope for this milestone."""
    routes = routes if routes is not None else DEFAULT_ROUTES
    q = query.lower()
    types: list[str] = []
    for keywords, mtype in routes:
        if any(k in q for k in keywords) and mtype not in types:
            types.append(mtype)
    return RetrievalIntent(memory_types=types or None)

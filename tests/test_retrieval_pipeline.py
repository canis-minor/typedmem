"""Minimal typed retrieval pipeline (v0) — router, filters, resolver, e2e."""

from datetime import datetime, timedelta, timezone

from typedmem import (
    HashingEmbeddingProvider,
    InMemoryStore,
    Memory,
    MemoryType,
    Transition,
    TypedRetriever,
    route_query,
)
from typedmem.retrieval import (
    RetrievalFilters,
    apply_filters,
    latest_per_slot,
    remove_superseded,
    resolve_temporal,
)

JAN = datetime(2026, 1, 1, tzinfo=timezone.utc)
JUL = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _create(store, m):
    """Insert a memory verbatim (bypass conflict resolution), as a benchmark
    loader would when replaying a timeline."""
    store.apply_transition(Transition(action="create", memory=m, actor="system"))
    return m


# ── Feature 1: router ──────────────────────────────────────────────────────
def test_router_preference_query():
    assert route_query("what coffee do I prefer?").memory_types == ["preference"]


def test_router_decision_query():
    assert "decision" in (route_query("why did I decide to use Postgres?").memory_types or [])


def test_router_event_query():
    assert "event" in (route_query("what happened at the offsite?").memory_types or [])


def test_router_unknown_query_routes_to_nothing():
    assert route_query("xyzzy").memory_types is None


# ── Feature 2: filters ─────────────────────────────────────────────────────
def _mem(t, content, subject, status=None, ts=JUL):
    return Memory(type=t, content=content, subject=subject, status=status, timestamp=ts)


def test_filter_by_type():
    pref = _mem("preference", "likes tea", "drink")
    fact = _mem("fact", "water boils at 100C", "water")
    f = RetrievalFilters(memory_types=["preference"])
    assert f.matches(pref) is True
    assert f.matches(fact) is False


def test_filter_by_entity():
    a = _mem("preference", "loves espresso", "company:espresso")
    b = _mem("preference", "loves tea", "company:teahouse")
    got = apply_filters([a, b], RetrievalFilters(entity_ids=["company:espresso"]))
    assert got == [a]


def test_filter_by_status():
    active = _mem("goal", "ship v1", "proj", status="active")
    done = _mem("goal", "ship v0", "proj", status="resolved")
    got = apply_filters([active, done], RetrievalFilters(status="active"))
    assert got == [active]


def test_filter_as_of_excludes_future():
    old = _mem("event", "kickoff", "proj", ts=JAN)
    new = _mem("event", "launch", "proj", ts=JUL)
    got = apply_filters([old, new], RetrievalFilters(as_of=JAN))
    assert got == [old]


# ── Feature 4: resolver ────────────────────────────────────────────────────
def test_remove_superseded():
    live = _mem("preference", "current", "x")
    dead = _mem("preference", "old", "x")
    dead.superseded_by = live.id
    assert remove_superseded([live, dead]) == [live]


def test_latest_per_slot_keeps_newest_for_single_valued():
    old = _mem("preference", "startups", "companies", ts=JAN)
    new = _mem("preference", "mature companies", "companies", ts=JUL)
    got = latest_per_slot([old, new], types={"preference"})
    assert got == [new]


def test_latest_per_slot_leaves_multivalued_untouched():
    f1 = _mem("fact", "fact one", "topic", ts=JAN)
    f2 = _mem("fact", "fact two", "topic", ts=JUL)
    got = latest_per_slot([f1, f2], types={"preference"})  # facts not collapsed
    assert {m.id for m in got} == {f1.id, f2.id}


def test_resolve_temporal_combines_rules():
    old = _mem("preference", "startups", "companies", ts=JAN)
    new = _mem("preference", "mature companies", "companies", ts=JUL)
    superseded = _mem("preference", "gone", "drinks")
    superseded.superseded_by = "whatever"
    got = resolve_temporal([old, new, superseded], collapse_types={"preference"})
    assert got == [new]


# ── Retriever: end to end ──────────────────────────────────────────────────
def _retriever(store):
    return TypedRetriever(store, embedder=HashingEmbeddingProvider(dim=1024))


def test_end_to_end_returns_current_preference_dropping_stale():
    """Two same-slot preferences (Jan superseded by Jul) + an unrelated goal.
    Typed routing + temporal resolution should return only the July preference."""
    store = InMemoryStore()
    jan = _create(store, _mem("preference", "I like early-stage startups", "companies", ts=JAN))
    jul = _create(store, _mem("preference", "I now prefer mature established companies", "companies", ts=JUL))
    jan.superseded_by = jul.id
    store.apply_transition(Transition(action="update", memory_id=jan.id,
                                      changes={"superseded_by": jul.id}, actor="system"))
    _create(store, _mem("goal", "run a marathon this year", "fitness"))

    out = _retriever(store).retrieve("what kind of companies do I prefer these days?", top_k=5)
    assert len(out) == 1
    assert out[0].id == jul.id
    assert "mature" in out[0].content


def test_end_to_end_collapses_unsuperseded_duplicates_to_latest():
    """Even without an explicit supersede link, two same-slot preferences
    collapse to the newest (preference is single-valued under the default policy)."""
    store = InMemoryStore()
    _create(store, _mem("preference", "I like early-stage startups", "companies", ts=JAN))
    jul = _create(store, _mem("preference", "I now prefer mature established companies", "companies", ts=JUL))

    out = _retriever(store).retrieve("which companies do I prefer?", top_k=5)
    assert [m.id for m in out] == [jul.id]


def test_end_to_end_explicit_type_filter_overrides_router():
    store = InMemoryStore()
    _create(store, _mem("preference", "loves espresso", "drink"))
    goal = _create(store, _mem("goal", "learn espresso latte art", "skill"))
    # Query says "prefer" (routes to preference), but caller forces goal.
    out = _retriever(store).retrieve("what do I prefer to learn?", memory_types=["goal"], top_k=5)
    assert [m.id for m in out] == [goal.id]

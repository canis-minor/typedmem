"""Exercises every ConflictPolicy through MemoryStore.add()."""

from datetime import timedelta

from typed_memory import (
    ConflictPolicy,
    InMemoryStore,
    Memory,
    MemoryType,
    PolicyEngine,
    Source,
    TypePolicy,
)
from typed_memory.policy import DEFAULT_POLICIES
from typed_memory.schema import _now


def _engine_with(t: MemoryType, policy: ConflictPolicy, half_life=None) -> PolicyEngine:
    pols = dict(DEFAULT_POLICIES)
    pols[t] = TypePolicy(half_life_days=half_life, summarizable=False, conflict_policy=policy)
    return PolicyEngine(pols)


# ── REPLACE (preference default) ─────────────────────────────────────────────
def test_replace_merges_in_place():
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.PREFERENCE, "likes tea", confidence=0.7, subject="user"))
    b = store.add(Memory(MemoryType.PREFERENCE, "likes coffee", confidence=0.9, subject="user"))
    assert len(store) == 1
    assert a.id == b.id  # same id
    assert b.content == "likes coffee"


def test_replace_downgrades_to_ignore_when_weaker():
    store = InMemoryStore()
    store.add(Memory(MemoryType.PREFERENCE, "likes coffee", confidence=0.9, subject="user"))
    weaker = Memory(MemoryType.PREFERENCE, "likes water", confidence=0.4, subject="user",
                    timestamp=_now() - timedelta(days=1))
    store.add(weaker)
    assert len(store) == 1
    pref = store.by_type(MemoryType.PREFERENCE)[0]
    assert pref.content == "likes coffee"


# ── KEEP_BOTH (fact default) ─────────────────────────────────────────────────
def test_keep_both_stores_side_by_side():
    store = InMemoryStore()
    store.add(Memory(MemoryType.FACT, "lives in California", subject="user"))
    store.add(Memory(MemoryType.FACT, "lives in New York", subject="user"))
    assert len(store) == 2


# ── SUPERSEDE ────────────────────────────────────────────────────────────────
def test_supersede_marks_old_and_keeps_both():
    engine = _engine_with(MemoryType.GOAL, ConflictPolicy.SUPERSEDE)
    store = InMemoryStore(engine)
    old = store.add(Memory(MemoryType.GOAL, "ship v0.3", subject="proj"))
    new = store.add(Memory(MemoryType.GOAL, "ship v0.4", subject="proj"))
    assert len(store) == 2
    assert store.get(old.id).superseded_by == new.id
    # by_type defaults to filtering superseded out
    active = store.by_type(MemoryType.GOAL)
    assert len(active) == 1 and active[0].id == new.id
    # include_superseded shows both
    assert len(store.by_type(MemoryType.GOAL, include_superseded=True)) == 2


# ── REINFORCE ────────────────────────────────────────────────────────────────
def test_reinforce_merges_sources_and_boosts_confidence():
    engine = _engine_with(MemoryType.FACT, ConflictPolicy.REINFORCE)
    store = InMemoryStore(engine)
    a = store.add(Memory(
        MemoryType.FACT, "earth orbits sun", subject="astronomy",
        confidence=0.6, sources=[Source(document_id="doc1")],
    ))
    store.add(Memory(
        MemoryType.FACT, "earth orbits sun", subject="astronomy",
        confidence=0.8, sources=[Source(document_id="doc2")],
    ))
    assert len(store) == 1
    merged = store.get(a.id)
    assert {s.document_id for s in merged.sources} == {"doc1", "doc2"}
    assert merged.confidence > 0.6
    assert merged.confidence <= 1.0


def test_reinforce_dedupes_by_full_source_key():
    engine = _engine_with(MemoryType.FACT, ConflictPolicy.REINFORCE)
    store = InMemoryStore(engine)
    s1 = Source(document_id="d", chunk_id="c1", span=(0, 5))
    s2 = Source(document_id="d", chunk_id="c2", span=(0, 5))  # same doc, different chunk
    store.add(Memory(MemoryType.FACT, "claim", subject="t", confidence=0.6, sources=[s1]))
    store.add(Memory(MemoryType.FACT, "claim", subject="t", confidence=0.7, sources=[s2]))
    merged = store.by_type(MemoryType.FACT)[0]
    assert len(merged.sources) == 2  # different chunk_id keeps both


def test_reinforce_dedupes_identical_source():
    engine = _engine_with(MemoryType.FACT, ConflictPolicy.REINFORCE)
    store = InMemoryStore(engine)
    s = Source(document_id="d", chunk_id="c", span=(0, 5))
    store.add(Memory(MemoryType.FACT, "claim", subject="t", confidence=0.6, sources=[s]))
    store.add(Memory(MemoryType.FACT, "claim", subject="t", confidence=0.7, sources=[s]))
    merged = store.by_type(MemoryType.FACT)[0]
    assert len(merged.sources) == 1  # same key — deduped


# ── FLAG ─────────────────────────────────────────────────────────────────────
def test_flag_cross_links_conflicting_memories():
    engine = _engine_with(MemoryType.FACT, ConflictPolicy.FLAG)
    store = InMemoryStore(engine)
    a = store.add(Memory(MemoryType.FACT, "X", subject="t"))
    b = store.add(Memory(MemoryType.FACT, "Y", subject="t"))
    assert len(store) == 2
    assert store.get(a.id).metadata["conflicts_with"] == [b.id]
    assert store.get(b.id).metadata["conflicts_with"] == [a.id]


# ── IGNORE explicit ──────────────────────────────────────────────────────────
def test_ignore_policy_drops_incoming():
    engine = _engine_with(MemoryType.FACT, ConflictPolicy.IGNORE)
    store = InMemoryStore(engine)
    a = store.add(Memory(MemoryType.FACT, "first", subject="immutable"))
    store.add(Memory(MemoryType.FACT, "second", subject="immutable"))
    assert len(store) == 1
    assert store.get(a.id).content == "first"


# ── No subject = no conflict path ────────────────────────────────────────────
def test_subject_less_memories_never_collide():
    store = InMemoryStore()
    store.add(Memory(MemoryType.EVENT, "thing happened"))
    store.add(Memory(MemoryType.EVENT, "thing happened"))
    assert len(store) == 2

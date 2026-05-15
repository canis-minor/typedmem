"""ContradictionSurfacer: graph traversal over conflicts_with edges."""

from typedmem import (
    ConflictPolicy,
    ContradictionSurfacer,
    InMemoryStore,
    Memory,
    MemoryType,
    PolicyEngine,
    TypePolicy,
)


def _flag_engine() -> PolicyEngine:
    from typedmem.policy import DEFAULT_POLICIES
    pols = dict(DEFAULT_POLICIES)
    pols["fact"] = TypePolicy(None, False, ConflictPolicy.FLAG)
    return PolicyEngine(pols)


def test_no_contradictions_returns_empty():
    store = InMemoryStore()
    store.add(Memory(MemoryType.FACT, "x"))
    result = ContradictionSurfacer().evolve(store)
    assert result.records == []
    assert result.dry_run is True   # surfacer is always read-only


def test_two_flagged_memories_form_one_cluster():
    store = InMemoryStore(_flag_engine())
    store.add(Memory(MemoryType.FACT, "lives in CA", subject="user"))
    store.add(Memory(MemoryType.FACT, "lives in NY", subject="user"))
    result = ContradictionSurfacer().evolve(store)
    assert len(result.records) == 1
    assert len(result.records[0].input_ids) == 2


def test_three_way_chain_collapses_to_single_cluster():
    """A→B and B→C should be the same connected component."""
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.FACT, "A", subject="x"))
    b = store.add(Memory(MemoryType.FACT, "B", subject="x"))
    c = store.add(Memory(MemoryType.FACT, "C", subject="x"))
    # Hand-roll the edges A-B and B-C
    a.metadata["conflicts_with"] = [b.id]
    b.metadata["conflicts_with"] = [a.id, c.id]
    c.metadata["conflicts_with"] = [b.id]
    for m in (a, b, c):
        store._put(m)
    clusters = ContradictionSurfacer().clusters(store)
    assert len(clusters) == 1
    assert {m.id for m in clusters[0]} == {a.id, b.id, c.id}


def test_workspace_scope():
    store = InMemoryStore(_flag_engine())
    store.add(Memory(MemoryType.FACT, "x", subject="t", workspace="ws1"))
    store.add(Memory(MemoryType.FACT, "y", subject="t", workspace="ws1"))
    store.add(Memory(MemoryType.FACT, "x", subject="t", workspace="ws2"))
    store.add(Memory(MemoryType.FACT, "z", subject="t", workspace="ws2"))
    # Each workspace should see its own cluster only
    ws1 = ContradictionSurfacer().evolve(store, workspace="ws1")
    ws2 = ContradictionSurfacer().evolve(store, workspace="ws2")
    assert len(ws1.records) == 1 and len(ws2.records) == 1


def test_dangling_conflict_id_skipped():
    """A conflict pointer to a non-existent memory must not crash."""
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.FACT, "A"))
    a.metadata["conflicts_with"] = ["does-not-exist"]
    store._put(a)
    result = ContradictionSurfacer().evolve(store)
    assert result.records == []   # no peer found → not a cluster

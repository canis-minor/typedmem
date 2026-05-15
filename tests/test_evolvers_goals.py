"""GoalResolver: semantic match, dry-run, revert."""

from typedmem import (
    GoalResolver,
    GoalStatus,
    HashingEmbeddingProvider,
    InMemoryStore,
    Memory,
    MemoryType,
    revert_goal_resolution,
)


def _seed(store):
    g = store.add(Memory(MemoryType.GOAL, "learn to count to ten", subject="child"))
    e = store.add(Memory(MemoryType.EVENT, "child counted to ten today", subject="child"))
    return g, e


def test_matching_event_resolves_goal():
    store = InMemoryStore()
    g, e = _seed(store)
    resolver = GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2)
    result = resolver.evolve(store)
    assert len(result.records) == 1
    goal = store.get(g.id)
    assert goal.status == GoalStatus.RESOLVED
    assert goal.metadata["resolved_by"] == e.id
    assert goal.metadata["previous_status"] == "active"
    assert "evolution_history" in goal.metadata


def test_below_threshold_no_change():
    store = InMemoryStore()
    g, _ = _seed(store)
    resolver = GoalResolver(HashingEmbeddingProvider(dim=64), threshold=0.99)
    result = resolver.evolve(store)
    assert result.records == []
    assert store.get(g.id).status == GoalStatus.ACTIVE


def test_dry_run_returns_records_without_mutating():
    store = InMemoryStore()
    g, _ = _seed(store)
    resolver = GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2)
    result = resolver.evolve(store, dry_run=True)
    assert len(result.records) == 1
    assert result.dry_run is True
    assert store.get(g.id).status == GoalStatus.ACTIVE
    assert "previous_status" not in store.get(g.id).metadata


def test_revert_restores_previous_status():
    store = InMemoryStore()
    g, _ = _seed(store)
    GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2).evolve(store)
    assert store.get(g.id).status == GoalStatus.RESOLVED

    ok = revert_goal_resolution(store, g.id)
    assert ok is True
    m = store.get(g.id)
    assert m.status == "active"
    assert "previous_status" not in m.metadata
    assert "resolved_by" not in m.metadata


def test_revert_on_unresolved_returns_false():
    store = InMemoryStore()
    g, _ = _seed(store)
    assert revert_goal_resolution(store, g.id) is False


def test_no_active_goals_no_op():
    store = InMemoryStore()
    store.add(Memory(MemoryType.EVENT, "something happened"))
    resolver = GoalResolver(HashingEmbeddingProvider(), threshold=0.5)
    result = resolver.evolve(store)
    assert result.records == []


def test_workspace_scope():
    store = InMemoryStore()
    store.add(Memory(MemoryType.GOAL, "learn to walk", subject="c", workspace="alice"))
    store.add(Memory(MemoryType.EVENT, "child walked today", subject="c", workspace="bob"))
    resolver = GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2)
    # Each workspace is scoped — no cross-workspace match
    assert resolver.evolve(store, workspace="alice").records == []
    assert resolver.evolve(store, workspace="bob").records == []

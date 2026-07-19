"""GoalResolver: semantic match, dry-run, revert."""

import traceback

import pytest

from typedmem import (
    ConcurrencyError,
    GoalResolver,
    GoalStatus,
    HashingEmbeddingProvider,
    InMemoryStore,
    Memory,
    MemoryType,
    Transition,
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
    assert any(e.source == "evolver" for e in store.history(g.id))


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


# ── v0.8: routed through the TransitionEngine ──────────────────────────────
_ENGINE_FRAMES = {"_apply_update", "_apply_add", "_apply_conflict", "_apply_delete"}


def test_resolver_never_calls_put_directly():
    """Fails if GoalResolver (resolve or revert) mutates via ``store._put``
    without going through the TransitionEngine."""
    store = InMemoryStore()
    g, _ = _seed(store)  # seed BEFORE installing the spy
    orig_put = store._put
    direct_calls: list[str] = []

    def spy(m):
        frames = {f.name for f in traceback.extract_stack()}
        if _ENGINE_FRAMES.isdisjoint(frames):
            direct_calls.append(m.id)  # _put reached without the engine on the stack
        return orig_put(m)

    store._put = spy
    GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2).evolve(store)
    revert_goal_resolution(store, g.id)
    store._put = orig_put
    assert direct_calls == []


def test_resolve_then_revert_version_sequence():
    """goal v1 active → resolve(expected=1) → v2 resolved → revert(expected=2) → v3 active."""
    store = InMemoryStore()
    g, _ = _seed(store)
    assert store.get(g.id).version == 1
    GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2).evolve(store)
    resolved = store.get(g.id)
    assert resolved.status == GoalStatus.RESOLVED and resolved.version == 2
    assert revert_goal_resolution(store, g.id) is True
    reverted = store.get(g.id)
    assert reverted.status == "active" and reverted.version == 3


def test_resolve_event_carries_actor_reason_evidence_version():
    store = InMemoryStore()
    g, e = _seed(store)
    GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2).evolve(store)
    resolve_events = [ev for ev in store.history(g.id) if ev.action == "resolve"]
    assert len(resolve_events) == 1
    ev = resolve_events[0]
    assert ev.source == "evolver"
    assert ev.source_name == "goal_resolver"
    assert e.id in ev.input_ids               # evidence present
    assert "similarity" in ev.reason          # reason preserved
    assert ev.payload.get("version") == 2     # resulting version recorded


def test_stale_resolve_fails_without_partial_mutation():
    store = InMemoryStore()
    g, e = _seed(store)
    # Someone bumps the goal's version between load and resolve.
    store.apply_transition(
        Transition(action="update", memory_id=g.id, changes={"content": "changed"})
    )
    assert store.get(g.id).version == 2
    with pytest.raises(ConcurrencyError):
        store.apply_transition(
            Transition(
                action="resolve", memory_id=g.id, expected_version=1,
                changes={"status": "resolved", "metadata": {"resolved_by": e.id}},
                actor="evolver", actor_name="goal_resolver", evidence=[e.id],
            )
        )
    after = store.get(g.id)
    assert after.status == "active"           # unchanged
    assert after.version == 2                 # no bump
    assert "resolved_by" not in after.metadata  # no partial mutation

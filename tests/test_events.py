"""v0.6a memory event log: timeline queries, sources, delete survival, lazy
migration. Covers all three store backends to keep them in sync."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from typedmem import (
    AgentMemory,
    ConflictPolicy,
    EVENT_SOURCES,
    InMemoryStore,
    JSONLMemoryStore,
    Memory,
    MemoryEvent,
    MemoryType,
    PolicyEngine,
    SQLiteMemoryStore,
    TypePolicy,
)
from typedmem.evolvers import EvolutionRecord, annotate_history


# ── Helpers ─────────────────────────────────────────────────────────────────
def _engine_with(t: MemoryType, p: ConflictPolicy) -> PolicyEngine:
    eng = PolicyEngine()
    eng.policies[t.value] = TypePolicy(None, False, p)
    return eng


def _three_stores(tmp_path: Path):
    """Yield one of each backend, parametrized via pytest."""
    return [
        ("memory", InMemoryStore()),
        ("jsonl", JSONLMemoryStore(tmp_path / "store.jsonl")),
        ("sqlite", SQLiteMemoryStore(":memory:")),
    ]


# ── MemoryEvent dataclass ───────────────────────────────────────────────────
def test_memory_event_round_trip():
    e = MemoryEvent(
        memory_id="m1", workspace="w", type="fact", subject="s",
        action="added", source="agent", source_name="caller",
        reason="r", input_ids=["m1"], output_ids=["m1"],
        payload={"k": "v"},
    )
    e2 = MemoryEvent.from_dict(e.to_dict())
    assert e2.memory_id == "m1"
    assert e2.source == "agent"
    assert e2.source_name == "caller"
    assert e2.payload == {"k": "v"}
    assert e2.timestamp == e.timestamp


def test_memory_event_rejects_invalid_source():
    with pytest.raises(ValueError):
        MemoryEvent(memory_id="m1", workspace="w", action="added", source="bogus")


def test_event_sources_set_is_canonical():
    assert EVENT_SOURCES == {"store", "evolver", "agent", "user", "system"}


# ── Every add emits an "added" event (canonical change feed) ────────────────
@pytest.mark.parametrize("backend", ["memory", "jsonl", "sqlite"])
def test_add_emits_added_event_on_every_backend(backend, tmp_path):
    stores = dict(_three_stores(tmp_path))
    store = stores[backend]
    m = store.add(Memory(MemoryType.FACT, "X"))
    events = store.history(m.id)
    assert len(events) == 1
    assert events[0].action == "added"
    assert events[0].source == "store"
    assert events[0].memory_id == m.id


def test_add_with_subject_no_collision_still_emits():
    store = InMemoryStore()
    m = store.add(Memory(MemoryType.FACT, "X", subject="t"))
    events = store.history(m.id)
    assert [e.action for e in events] == ["added"]


# ── Delete event outlives the memory ───────────────────────────────────────
@pytest.mark.parametrize("backend", ["memory", "jsonl", "sqlite"])
def test_delete_event_survives_memory(backend, tmp_path):
    stores = dict(_three_stores(tmp_path))
    store = stores[backend]
    m = store.add(Memory(MemoryType.FACT, "X"))
    mid = m.id
    assert store.delete(mid) is True
    assert store.get(mid) is None  # row is gone
    events = store.history(mid)    # but event log keeps it
    assert any(e.action == "deleted" for e in events)
    assert any(e.action == "added" for e in events)


def test_delete_of_missing_memory_emits_nothing():
    store = InMemoryStore()
    assert store.delete("nonexistent") is False
    # No events should have been written for the missing id.
    assert store.history("nonexistent") == []


# ── Source tagging ──────────────────────────────────────────────────────────
def test_agent_memory_remember_tags_source_agent(tmp_path):
    mem = AgentMemory(path=":memory:")
    added = mem.remember("User wants to learn Rust")
    assert added  # rule extractor produced at least one
    for m in added:
        events = mem.store.history(m.id)
        # Find the agent-tagged add
        agent_adds = [e for e in events if e.source == "agent" and e.action == "added"]
        assert agent_adds, f"no agent-tagged add for {m.id!r}: {events}"
        assert agent_adds[0].source_name == "AgentMemory.remember"


def test_agent_memory_forget_tags_source_agent():
    mem = AgentMemory(path=":memory:")
    m = mem.store.add(Memory(MemoryType.FACT, "X"))
    mem.forget(m.id)
    events = mem.store.history(m.id)
    del_events = [e for e in events if e.action == "deleted"]
    assert del_events and del_events[0].source == "agent"
    assert del_events[0].source_name == "AgentMemory.forget"


def test_add_with_user_source_tag():
    store = InMemoryStore()
    m = store.add(
        Memory(MemoryType.FACT, "X"),
        event_source="user", event_source_name="cli:remember",
    )
    events = store.history(m.id)
    assert events[0].source == "user"
    assert events[0].source_name == "cli:remember"


def test_invalid_event_source_raises():
    store = InMemoryStore()
    with pytest.raises(ValueError):
        store.add(Memory(MemoryType.FACT, "X"), event_source="badsrc")


# ── Conflict events ─────────────────────────────────────────────────────────
def test_replace_emits_replaced_event():
    store = InMemoryStore()  # preference defaults to REPLACE
    a = store.add(Memory(MemoryType.PREFERENCE, "v0", subject="u", confidence=0.5))
    store.add(Memory(MemoryType.PREFERENCE, "v1", subject="u", confidence=0.6))
    actions = [e.action for e in store.history(a.id)]
    assert actions == ["added", "replaced"]


def test_supersede_emits_paired_events():
    engine = _engine_with(MemoryType.GOAL, ConflictPolicy.SUPERSEDE)
    store = InMemoryStore(engine)
    old = store.add(Memory(MemoryType.GOAL, "g0", subject="p"))
    new = store.add(Memory(MemoryType.GOAL, "g1", subject="p"))
    old_actions = [e.action for e in store.history(old.id)]
    new_actions = [e.action for e in store.history(new.id)]
    assert "superseded" in old_actions
    assert "supersedes" in new_actions


# ── Timeline queries ────────────────────────────────────────────────────────
def test_timeline_filters_by_subject_type_workspace():
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.FACT, "alpha", subject="x"))
    b = store.add(Memory(MemoryType.GOAL, "beta", subject="y"))
    c = store.add(Memory(MemoryType.FACT, "gamma", subject="x", workspace="other"))

    by_subject = store.timeline(subject="x")
    assert {e.memory_id for e in by_subject} == {a.id, c.id}

    by_type = store.timeline(type="goal")
    assert {e.memory_id for e in by_type} == {b.id}

    by_ws = store.timeline(workspace="other")
    assert {e.memory_id for e in by_ws} == {c.id}

    # All filters combined
    by_all = store.timeline(subject="x", type="fact", workspace="default")
    assert {e.memory_id for e in by_all} == {a.id}


def test_timeline_filters_by_source():
    store = InMemoryStore()
    store.add(Memory(MemoryType.FACT, "X"), event_source="user")
    store.add(Memory(MemoryType.FACT, "Y"), event_source="agent")
    user_only = store.timeline(source="user")
    agent_only = store.timeline(source="agent")
    assert len(user_only) == 1 and user_only[0].source == "user"
    assert len(agent_only) == 1 and agent_only[0].source == "agent"


def test_timeline_ordered_by_timestamp(tmp_path):
    store = SQLiteMemoryStore(":memory:")
    store.add(Memory(MemoryType.FACT, "first", subject="s"))
    time.sleep(0.001)
    store.add(Memory(MemoryType.FACT, "second", subject="s2"))
    events = store.timeline()
    assert all(events[i].timestamp <= events[i + 1].timestamp for i in range(len(events) - 1))


def test_timeline_rejects_invalid_source():
    store = InMemoryStore()
    with pytest.raises(ValueError):
        store.timeline(source="bogus")


# ── changed_since() change feed ────────────────────────────────────────────
@pytest.mark.parametrize("backend", ["memory", "jsonl", "sqlite"])
def test_changed_since_returns_strictly_newer_events(backend, tmp_path):
    stores = dict(_three_stores(tmp_path))
    store = stores[backend]
    store.add(Memory(MemoryType.FACT, "before"))
    cutoff = datetime.now(timezone.utc)
    time.sleep(0.01)  # ensure later events have strictly greater timestamps
    m_after = store.add(Memory(MemoryType.FACT, "after"))
    changes = store.changed_since(cutoff)
    assert any(e.memory_id == m_after.id for e in changes)
    assert all(e.timestamp > cutoff for e in changes)


def test_changed_since_includes_deletes():
    store = InMemoryStore()
    m = store.add(Memory(MemoryType.FACT, "X"))
    cutoff = datetime.now(timezone.utc)
    time.sleep(0.01)
    store.delete(m.id)
    changes = store.changed_since(cutoff)
    assert any(e.action == "deleted" and e.memory_id == m.id for e in changes)


# ── Lazy migration from metadata["evolution_history"] ───────────────────────
def test_lazy_migration_promotes_legacy_metadata_history():
    """A memory written under v0.5 (pre-events) had its audit in
    metadata['evolution_history']. On first history() call, those entries
    migrate into the event log with source='system'."""
    store = InMemoryStore()
    m = Memory(MemoryType.FACT, "X")
    # Simulate a v0.5 memory with legacy history present.
    m.metadata["evolution_history"] = [{
        "evolver": "store",
        "action": "legacy_replaced",
        "input_ids": [m.id],
        "output_ids": [m.id],
        "reason": "from old DB",
        "timestamp": "2025-01-01T00:00:00+00:00",
    }]
    store._put(m)  # bypass add() so no v0.6 event is emitted

    events = store.history(m.id)
    assert len(events) == 1
    assert events[0].action == "legacy_replaced"
    assert events[0].source == "system"
    assert events[0].source_name == "migrate_evolution_history"
    assert events[0].payload.get("legacy_evolver") == "store"
    # And the legacy key has been cleared from the memory's metadata
    assert "evolution_history" not in store.get(m.id).metadata


def test_migration_is_idempotent():
    store = InMemoryStore()
    m = Memory(MemoryType.FACT, "X")
    m.metadata["evolution_history"] = [{
        "evolver": "store", "action": "x", "input_ids": [], "output_ids": [],
        "reason": "", "timestamp": "2025-01-01T00:00:00+00:00",
    }]
    store._put(m)
    first = store.history(m.id)
    second = store.history(m.id)
    assert len(first) == len(second) == 1


def test_legacy_evolution_history_api_reads_from_event_log():
    """The pre-v0.6 dict-shaped evolution_history(memory_id) API still works
    and is backed by the new event log."""
    store = InMemoryStore()
    m = store.add(Memory(MemoryType.PREFERENCE, "v0", subject="u", confidence=0.5))
    store.add(Memory(MemoryType.PREFERENCE, "v1", subject="u", confidence=0.6))
    hist = store.evolution_history(m.id)
    assert isinstance(hist, list)
    assert all(isinstance(e, dict) for e in hist)
    actions = [e["action"] for e in hist]
    assert "added" in actions
    assert "replaced" in actions


# ── Evolver writes through to the event log ────────────────────────────────
def test_annotate_history_emits_evolver_event():
    store = InMemoryStore()
    m = store.add(Memory(MemoryType.FACT, "X"))
    record = EvolutionRecord(
        evolver="test_evolver", action="annotate",
        input_ids=[m.id], output_ids=[m.id], reason="manual test",
    )
    annotate_history(store, m, record)
    events = store.history(m.id)
    evolver_events = [e for e in events if e.source == "evolver"]
    assert len(evolver_events) == 1
    assert evolver_events[0].source_name == "test_evolver"
    assert evolver_events[0].action == "annotate"


# ── JSONL sidecar file persistence ─────────────────────────────────────────
def test_jsonl_events_survive_reopen(tmp_path):
    path = tmp_path / "store.jsonl"
    s1 = JSONLMemoryStore(path)
    m = s1.add(Memory(MemoryType.FACT, "X"))
    s1.close()

    s2 = JSONLMemoryStore(path)
    events = s2.history(m.id)
    assert events and events[0].action == "added"


# ── SQLite events table persists with the DB ───────────────────────────────
def test_sqlite_events_survive_reopen(tmp_path):
    db = tmp_path / "store.db"
    s1 = SQLiteMemoryStore(db)
    m = s1.add(Memory(MemoryType.FACT, "X"))
    s1.close()

    s2 = SQLiteMemoryStore(db)
    events = s2.history(m.id)
    assert events and events[0].action == "added"

"""PreferenceDriftDetector flags churn over a trailing window."""

from datetime import datetime, timedelta, timezone

from typedmem import (
    InMemoryStore,
    Memory,
    MemoryType,
    PreferenceDriftDetector,
)


def _make_drifting(store, *, churn: int = 5):
    """Insert one slot then REPLACE it `churn` times."""
    store.add(Memory(MemoryType.PREFERENCE, "v0", subject="user", confidence=0.5))
    for i in range(1, churn + 1):
        store.add(Memory(
            MemoryType.PREFERENCE, f"v{i}", subject="user",
            confidence=0.5 + i * 0.01,
        ))


def test_below_threshold_emits_no_record():
    store = InMemoryStore()
    _make_drifting(store, churn=2)
    result = PreferenceDriftDetector(min_replaces=3).evolve(store)
    assert result.records == []


def test_above_threshold_emits_record_and_annotates():
    store = InMemoryStore()
    _make_drifting(store, churn=5)
    result = PreferenceDriftDetector(min_replaces=3).evolve(store)
    assert len(result.records) == 1
    m = store.by_type(MemoryType.PREFERENCE)[0]
    assert m.metadata.get("drift_flags")
    assert any(
        e.source == "evolver" and e.source_name == "preference_drift_detector"
        for e in store.history(m.id)
    )


def test_dry_run_emits_record_without_annotating():
    store = InMemoryStore()
    _make_drifting(store, churn=5)
    result = PreferenceDriftDetector(min_replaces=3).evolve(store, dry_run=True)
    assert len(result.records) == 1
    m = store.by_type(MemoryType.PREFERENCE)[0]
    assert "drift_flags" not in m.metadata
    drift_events = [
        e for e in store.history(m.id)
        if e.source_name == "preference_drift_detector"
    ]
    assert drift_events == []


def test_window_excludes_old_replaces():
    """Replaces outside the window don't count."""
    store = InMemoryStore()
    m = store.add(Memory(MemoryType.PREFERENCE, "v0", subject="user", confidence=0.5))
    # Inject 5 old timestamps into the log directly
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    m.metadata["replace_log"] = [old] * 5
    m.metadata["replace_count"] = 5
    store._put(m)
    result = PreferenceDriftDetector(min_replaces=3, window_days=30.0).evolve(store)
    assert result.records == []


def test_workspace_scoping():
    store = InMemoryStore()
    for ws in ("alice", "bob"):
        store.add(Memory(MemoryType.PREFERENCE, "v0", subject="u", workspace=ws, confidence=0.5))
        for i in range(1, 5):
            store.add(Memory(
                MemoryType.PREFERENCE, f"v{i}", subject="u", workspace=ws,
                confidence=0.5 + i * 0.01,
            ))
    alice = PreferenceDriftDetector(min_replaces=3).evolve(store, workspace="alice")
    assert len(alice.records) == 1
    assert alice.records[0].input_ids[0] != ""  # not bob's id


def test_type_filter():
    store = InMemoryStore()
    _make_drifting(store, churn=5)  # preference churns
    # GOAL never gets replace_log written in our default policy (REPLACE),
    # but force types=("goal",) to test the filter
    result = PreferenceDriftDetector(min_replaces=3, types=("goal",)).evolve(store)
    assert result.records == []

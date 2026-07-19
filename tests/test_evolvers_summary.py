"""SummaryEvolver: non-destructive in v0.4c."""

import traceback
from datetime import timedelta

from typedmem import (
    FakeClient,
    InMemoryStore,
    Memory,
    MemoryType,
    SummaryEvolver,
)
from typedmem.schema import _now

_ENGINE_FRAMES = {
    "_apply_update", "_apply_add", "_apply_create", "_apply_conflict", "_apply_delete",
}


def _stale_cluster(store, n=3):
    """Insert n EVENT memories that are old enough to have decayed past 0.3."""
    old_ts = _now() - timedelta(days=180)   # event half-life is 14d → very stale
    for i in range(n):
        store.add(Memory(
            MemoryType.EVENT, f"event {i} happened", subject="child",
            confidence=0.7, timestamp=old_ts,
        ))


def test_creates_summary_without_modifying_originals():
    store = InMemoryStore()
    _stale_cluster(store, n=3)
    pre_ids = [m.id for m in store]

    client = FakeClient("Child reached three milestones over the period.")
    SummaryEvolver(client, min_cluster_size=3).evolve(store)

    # All originals still present, untouched (no superseded_by, content same)
    for original_id in pre_ids:
        m = store.get(original_id)
        assert m is not None
        assert m.superseded_by is None
        assert m.content.startswith("event ")

    # New summary memory exists with summarizes pointing back
    summaries = [m for m in store if "summarizes" in m.metadata]
    assert len(summaries) == 1
    assert set(summaries[0].metadata["summarizes"]) == set(pre_ids)


def test_dry_run_creates_no_memory():
    store = InMemoryStore()
    _stale_cluster(store, n=3)
    pre_count = len(store)

    result = SummaryEvolver(FakeClient("won't be called")).evolve(store, dry_run=True)
    assert len(result.records) == 1
    assert len(store) == pre_count


def test_cluster_below_min_size_skipped():
    store = InMemoryStore()
    _stale_cluster(store, n=2)   # below default min=3
    SummaryEvolver(FakeClient("x")).evolve(store)
    summaries = [m for m in store if "summarizes" in m.metadata]
    assert summaries == []


def test_confident_memories_skipped():
    """Recent / high-confidence memories don't get summarized."""
    store = InMemoryStore()
    for i in range(5):
        store.add(Memory(MemoryType.EVENT, f"fresh event {i}", subject="child"))
    SummaryEvolver(FakeClient("x")).evolve(store)
    summaries = [m for m in store if "summarizes" in m.metadata]
    assert summaries == []


def test_summary_not_summarized_again():
    """A summary memory shouldn't itself be eligible to be summarized."""
    store = InMemoryStore()
    _stale_cluster(store, n=3)
    SummaryEvolver(FakeClient("first summary")).evolve(store)
    # Run again — the summary exists but has "summarizes" in metadata,
    # so it should be excluded from candidate clusters.
    SummaryEvolver(FakeClient("second summary")).evolve(store)
    summaries = [m for m in store if "summarizes" in m.metadata]
    assert len(summaries) == 1   # still just the first one


def test_audit_record_has_correct_io():
    store = InMemoryStore()
    _stale_cluster(store, n=3)
    pre_ids = [m.id for m in store]
    result = SummaryEvolver(FakeClient("summary text")).evolve(store)
    record = result.records[0]
    assert set(record.input_ids) == set(pre_ids)
    assert len(record.output_ids) == 1
    assert record.action == "create"


def test_empty_llm_response_skipped():
    """If the LLM returns empty, no summary memory is created."""
    store = InMemoryStore()
    _stale_cluster(store, n=3)
    result = SummaryEvolver(FakeClient("")).evolve(store)
    assert len(result.records) == 1
    assert result.records[0].output_ids == []
    summaries = [m for m in store if "summarizes" in m.metadata]
    assert summaries == []


# ── v0.8: routed through the TransitionEngine ──────────────────────────────
def test_summary_evolver_never_calls_put_directly():
    store = InMemoryStore()
    _stale_cluster(store, n=3)  # seed before installing the spy
    orig_put = store._put
    direct_calls: list[str] = []

    def spy(m):
        frames = {f.name for f in traceback.extract_stack()}
        if _ENGINE_FRAMES.isdisjoint(frames):
            direct_calls.append(m.id)
        return orig_put(m)

    store._put = spy
    result = SummaryEvolver(FakeClient("a condensed summary"), min_cluster_size=3).evolve(store)
    store._put = orig_put
    assert len(result.records) == 1     # a summary was actually created
    assert direct_calls == []           # ...and every _put went via the engine


def test_summary_created_at_v1_and_originals_bumped():
    store = InMemoryStore()
    _stale_cluster(store, n=3)
    original_versions = {m.id: m.version for m in store}
    SummaryEvolver(FakeClient("a condensed summary"), min_cluster_size=3).evolve(store)

    summary = next(m for m in store if "summarizes" in m.metadata)
    assert summary.version == 1  # raw create begins at version 1

    # Each original was annotated with summarized_by → exactly one version bump.
    for oid, v0 in original_versions.items():
        after = store.get(oid)
        assert after.metadata.get("summarized_by") == summary.id
        assert after.version == v0 + 1

    # The summary's create event is recorded with action "create".
    create_events = [e for e in store.history(summary.id) if e.action == "create"]
    assert len(create_events) == 1
    assert create_events[0].source == "evolver"
    assert create_events[0].source_name == "summary_evolver"

"""RFC-0001 kernel: version field, Transition/TransitionEngine funnel,
optimistic concurrency, and pluggable IdentityStrategy."""

import sqlite3
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from typedmem import (
    ConcurrencyError,
    ConflictPolicy,
    FakeClient,
    GoalResolver,
    HashingEmbeddingProvider,
    IdentityStrategy,
    InMemoryStore,
    JSONLMemoryStore,
    Memory,
    MemoryType,
    PolicyEngine,
    PreferenceDriftDetector,
    SQLiteMemoryStore,
    Source,
    SummaryEvolver,
    Transition,
    TypePolicy,
)


def _pref(subject: str, content: str, confidence: float = 0.8) -> Memory:
    return Memory(
        type="preference", content=content, subject=subject,
        confidence=confidence, sources=[Source(document_id=f"doc-{content}")],
    )


# ── version field ─────────────────────────────────────────────────────────
def test_fresh_memory_starts_at_version_1():
    assert Memory(type="fact", content="x").version == 1


def test_version_round_trips_through_dict():
    m = Memory(type="fact", content="x", version=4)
    assert Memory.from_dict(m.to_dict()).version == 4


def test_replace_bumps_version():
    store = InMemoryStore()
    m = store.add(_pref("coffee", "black", 0.6))
    assert m.version == 1
    # Stronger incoming on the same slot → REPLACE (preference default).
    store.add(_pref("coffee", "oat milk", 0.9))
    assert store.get(m.id).version == 2


def test_reinforce_bumps_version():
    policy = PolicyEngine(
        {"claim": TypePolicy(None, False, ConflictPolicy.REINFORCE)},
        default=TypePolicy(None, False, ConflictPolicy.KEEP_BOTH),
    )
    store = InMemoryStore(policy)
    a = Memory(type="claim", content="sky is blue", subject="sky",
               confidence=0.5, sources=[Source(document_id="d1")])
    m = store.add(a)
    b = Memory(type="claim", content="sky is blue", subject="sky",
               confidence=0.5, sources=[Source(document_id="d2")])
    store.add(b)
    assert store.get(m.id).version == 2


def test_sqlite_persists_version(tmp_path: Path):
    path = tmp_path / "v.db"
    with SQLiteMemoryStore(path) as s:
        m = s.add(_pref("tea", "green", 0.6))
        s.add(_pref("tea", "oolong", 0.9))  # REPLACE → version 2
    with SQLiteMemoryStore(path) as s:
        assert s.get(m.id).version == 2


def test_old_sqlite_db_migrates_version_to_1(tmp_path: Path):
    """A DB whose ``memories`` table predates the version column opens with
    version == 1 via the idempotent ALTER."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, content TEXT NOT NULL,
            confidence REAL NOT NULL, timestamp TEXT NOT NULL, subject TEXT,
            tags TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL, status TEXT
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO memories (id, type, content, confidence, timestamp, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        ("m-old", "fact", "legacy", 0.9, now, now),
    )
    conn.commit()
    conn.close()
    with SQLiteMemoryStore(path) as s:
        assert s.get("m-old").version == 1


# ── Transition / TransitionEngine funnel ──────────────────────────────────
def test_update_transition_applies_changes_and_bumps_version():
    store = InMemoryStore()
    m = store.add(_pref("editor", "vim"))
    result = store.apply_transition(
        Transition(action="update", memory_id=m.id,
                   changes={"content": "emacs"}, actor="user", reason="switched")
    )
    assert result.content == "emacs"
    assert store.get(m.id).version == 2
    actions = [e.action for e in store.history(m.id)]
    assert "update" in actions  # the transition emitted a typed event


def test_optimistic_concurrency_matching_version_succeeds():
    store = InMemoryStore()
    m = store.add(_pref("editor", "vim"))  # version 1
    store.apply_transition(
        Transition(action="update", memory_id=m.id, expected_version=1,
                   changes={"content": "emacs"})
    )
    assert store.get(m.id).content == "emacs"


def test_optimistic_concurrency_stale_version_raises_and_changes_nothing():
    store = InMemoryStore()
    m = store.add(_pref("editor", "vim"))  # version 1
    store.apply_transition(
        Transition(action="update", memory_id=m.id, changes={"content": "emacs"})
    )  # now version 2
    with pytest.raises(ConcurrencyError):
        store.apply_transition(
            Transition(action="update", memory_id=m.id, expected_version=1,
                       changes={"content": "nano"})
        )
    # A rejected transition changes no version and no content.
    after = store.get(m.id)
    assert after.version == 2
    assert after.content == "emacs"


def test_event_records_resulting_version():
    store = InMemoryStore()
    m = store.add(_pref("coffee", "black", 0.6))
    store.add(_pref("coffee", "oat milk", 0.9))  # REPLACE → version 2
    events = store.history(m.id)
    added = next(e for e in events if e.action == "added")
    replaced = next(e for e in events if e.action == "replaced")
    assert added.payload.get("version") == 1
    assert replaced.payload.get("version") == 2


def test_version_invariant_insert_mutate_ignore():
    """Insert → 1; one mutation → +1 exactly; a rejected (IGNORE) add → no bump."""
    store = InMemoryStore()
    m = store.add(_pref("coffee", "black", 0.9))
    assert store.get(m.id).version == 1
    store.add(_pref("coffee", "oat milk", 0.95))  # stronger → REPLACE
    assert store.get(m.id).version == 2
    store.add(_pref("coffee", "weak guess", 0.1))  # weaker → IGNORE, untouched
    assert store.get(m.id).version == 2


def test_delete_still_funnels_and_emits_event():
    store = InMemoryStore()
    m = store.add(_pref("editor", "vim"))
    assert store.delete(m.id) is True
    assert store.get(m.id) is None
    # The delete event survives in the log after the row is gone.
    assert any(e.action == "deleted" for e in store.history(m.id))


# ── pluggable IdentityStrategy ─────────────────────────────────────────────
class _TypeOnlyIdentity(IdentityStrategy):
    """Ignores subject: all memories of the same (workspace, type) share a slot."""

    def key_for(self, m: Memory) -> tuple:
        return (m.workspace, m.type)


def test_default_identity_keeps_distinct_subjects_separate():
    store = InMemoryStore()
    store.add(_pref("coffee", "black", 0.9))
    store.add(_pref("tea", "green", 0.9))
    assert len(store.all()) == 2


def test_custom_identity_collapses_by_type():
    store = InMemoryStore(identity=_TypeOnlyIdentity())
    store.add(_pref("coffee", "black", 0.6))
    store.add(_pref("tea", "green", 0.9))  # same (ws, type) slot → REPLACE
    prefs = store.all()
    assert len(prefs) == 1


# ── systemic guard: the engine is the sole mutator ─────────────────────────
# Sanctioned callers of _put: the TransitionEngine, and the store's own
# legacy-history migration maintenance path.
_ALLOWED_PUT_FRAMES = {
    "_apply_update", "_apply_add", "_apply_create", "_apply_conflict",
    "_apply_delete", "_migrate_legacy_history",
}


def test_no_mutation_escapes_the_engine():
    """Across store add/replace/delete AND every mutating evolver, no _put
    happens without the TransitionEngine (or the sanctioned migration path)
    on the call stack. Fails if any code reintroduces a direct _put."""
    store = InMemoryStore()

    # Seed a broad scenario BEFORE installing the spy.
    store.add(Memory(MemoryType.GOAL, "learn to count to ten", subject="child"))
    store.add(Memory(MemoryType.EVENT, "child counted to ten today", subject="child"))
    store.add(_pref("coffee", "black", 0.5))
    for i in range(4):  # churn to build replace_log for drift
        store.add(_pref("coffee", f"blend {i}", 0.5 + i * 0.02))
    old = _now_utc() - timedelta(days=180)
    for i in range(3):  # stale cluster for summary
        store.add(Memory(MemoryType.OBSERVATION, f"obs {i}", subject="s",
                         confidence=0.7, timestamp=old))

    orig_put = store._put
    offenders: list[str] = []

    def spy(m):
        frames = {f.name for f in traceback.extract_stack()}
        if _ALLOWED_PUT_FRAMES.isdisjoint(frames):
            offenders.append(m.id)
        return orig_put(m)

    store._put = spy
    # Store ops
    store.add(_pref("coffee", "definitive oat", 0.99))   # REPLACE conflict
    victim = store.add(Memory(MemoryType.FACT, "temp", subject="x"))
    store.delete(victim.id)
    # Every mutating evolver
    GoalResolver(HashingEmbeddingProvider(dim=1024), threshold=0.2).evolve(store)
    PreferenceDriftDetector(min_replaces=3).evolve(store)
    SummaryEvolver(FakeClient("condensed"), min_cluster_size=3,
                   cluster_types=("observation",)).evolve(store)
    store._put = orig_put

    assert offenders == []


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

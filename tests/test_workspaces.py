"""Workspace isolation, default scoping, enumeration."""

from pathlib import Path

from typedmem import (
    HashingEmbeddingProvider,
    InMemoryStore,
    JSONLMemoryStore,
    Memory,
    MemoryType,
    Retriever,
    SQLiteMemoryStore,
)


def _make_two_workspace_store():
    store = InMemoryStore()
    store.add(Memory(MemoryType.PREFERENCE, "likes tea", subject="user", workspace="alice"))
    store.add(Memory(MemoryType.PREFERENCE, "likes coffee", subject="user", workspace="bob"))
    return store


def test_same_subject_in_two_workspaces_does_not_merge():
    store = _make_two_workspace_store()
    assert len(store) == 2
    alice = store.by_type(MemoryType.PREFERENCE, workspace="alice")
    bob = store.by_type(MemoryType.PREFERENCE, workspace="bob")
    assert alice[0].content == "likes tea"
    assert bob[0].content == "likes coffee"


def test_default_workspace_scopes_queries():
    store = _make_two_workspace_store()
    store.add(Memory(MemoryType.FACT, "x"))  # default workspace
    assert len(store.all()) == 1


def test_workspaces_enumerated():
    store = _make_two_workspace_store()
    assert set(store.workspaces()) == {"alice", "bob"}


def test_retriever_scopes_by_workspace():
    store = _make_two_workspace_store()
    r = Retriever(store, embedder=HashingEmbeddingProvider())
    alice_hits = r.relevant("tea", workspace="alice")
    bob_hits = r.relevant("tea", workspace="bob")
    assert alice_hits and alice_hits[0].memory.workspace == "alice"
    # bob has no tea memory; if there's a hit it's still only from his workspace
    assert all(h.memory.workspace == "bob" for h in bob_hits)


def test_sqlite_workspace_index_and_enumeration(tmp_path: Path):
    with SQLiteMemoryStore(tmp_path / "m.db") as s:
        s.add(Memory(MemoryType.FACT, "f1", workspace="ws1"))
        s.add(Memory(MemoryType.FACT, "f2", workspace="ws2"))
        assert set(s.workspaces()) == {"ws1", "ws2"}
        assert len(s.by_type(MemoryType.FACT, workspace="ws1")) == 1


def test_jsonl_workspace_persists(tmp_path: Path):
    path = tmp_path / "m.jsonl"
    s1 = JSONLMemoryStore(path)
    s1.add(Memory(MemoryType.PREFERENCE, "likes tea", subject="user", workspace="alice"))
    s1.add(Memory(MemoryType.PREFERENCE, "likes coffee", subject="user", workspace="bob"))

    s2 = JSONLMemoryStore(path)
    assert set(s2.workspaces()) == {"alice", "bob"}
    assert len(s2.by_type(MemoryType.PREFERENCE, workspace="alice")) == 1


def test_store_default_workspace_override():
    store = InMemoryStore(default_workspace="legal")
    store.add(Memory(MemoryType.FACT, "x"))  # uses memory.workspace default "default"
    assert store.all(workspace="default")  # the memory landed in 'default'
    assert not store.all()                  # store's default workspace 'legal' is empty

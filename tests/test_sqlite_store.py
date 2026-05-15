from pathlib import Path

from typed_memory import Memory, MemoryType, SQLiteMemoryStore


def test_round_trip_across_reopen(tmp_path: Path):
    path = tmp_path / "m.db"
    s1 = SQLiteMemoryStore(path)
    m = s1.add(Memory(MemoryType.PREFERENCE, "likes tea", subject="user", tags=["beverage"]))
    s1.close()

    s2 = SQLiteMemoryStore(path)
    got = s2.get(m.id)
    assert got is not None
    assert got.content == "likes tea"
    assert got.subject == "user"
    assert got.tags == ["beverage"]
    s2.close()


def test_preference_merges_via_same_slot(tmp_path: Path):
    path = tmp_path / "m.db"
    with SQLiteMemoryStore(path) as s:
        s.add(Memory(MemoryType.PREFERENCE, "likes tea", subject="user", confidence=0.7))
        s.add(Memory(MemoryType.PREFERENCE, "likes coffee", subject="user", confidence=0.9))
        assert len(s) == 1
        assert s.by_type(MemoryType.PREFERENCE)[0].content == "likes coffee"


def test_by_type_index(tmp_path: Path):
    with SQLiteMemoryStore(tmp_path / "m.db") as s:
        s.add(Memory(MemoryType.FACT, "f"))
        s.add(Memory(MemoryType.EVENT, "e"))
        assert len(s.by_type(MemoryType.FACT)) == 1
        assert len(s.by_type(MemoryType.EVENT)) == 1


def test_in_memory_db():
    with SQLiteMemoryStore(":memory:") as s:
        s.add(Memory(MemoryType.GOAL, "ship v0.2"))
        assert len(s) == 1


def test_embedding_persisted(tmp_path: Path):
    path = tmp_path / "m.db"
    with SQLiteMemoryStore(path) as s:
        m = s.add(Memory(MemoryType.FACT, "hello"))
        s.set_embedding(m.id, [0.1, 0.2, 0.3], "test-embedder")

    with SQLiteMemoryStore(path) as s2:
        got = s2.get(m.id)
        assert got is not None
        assert got.metadata["_embedding"] == [0.1, 0.2, 0.3]
        assert got.metadata["_embedder_id"] == "test-embedder"

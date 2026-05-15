from typed_memory.schema import Memory, MemoryType
from typed_memory import InMemoryStore as MemoryStore


def test_add_and_get():
    store = MemoryStore()
    m = store.add(Memory(MemoryType.FACT, "x"))
    assert store.get(m.id) is m
    assert len(store) == 1


def test_preference_update_merges_same_subject():
    store = MemoryStore()
    a = store.add(Memory(MemoryType.PREFERENCE, "likes tea", confidence=0.7, subject="user"))
    b = store.add(Memory(MemoryType.PREFERENCE, "likes coffee", confidence=0.9, subject="user"))
    assert len(store) == 1
    assert a.id == b.id
    assert b.content == "likes coffee"


def test_fact_does_not_merge():
    store = MemoryStore()
    store.add(Memory(MemoryType.FACT, "x", subject="user"))
    store.add(Memory(MemoryType.FACT, "y", subject="user"))
    assert len(store) == 2


def test_delete():
    store = MemoryStore()
    m = store.add(Memory(MemoryType.EVENT, "went to park"))
    assert store.delete(m.id)
    assert store.get(m.id) is None

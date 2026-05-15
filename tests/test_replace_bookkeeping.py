"""REPLACE adds metadata['replace_log'] + replace_count for drift detection."""

from typedmem import InMemoryStore, Memory, MemoryType


def test_first_replace_creates_log():
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.PREFERENCE, "tea", subject="user", confidence=0.7))
    store.add(Memory(MemoryType.PREFERENCE, "coffee", subject="user", confidence=0.9))
    m = store.get(a.id)
    assert m.metadata["replace_count"] == 1
    assert len(m.metadata["replace_log"]) == 1


def test_log_grows_on_subsequent_replaces():
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.PREFERENCE, "tea", subject="user", confidence=0.7))
    for c, content in [(0.8, "coffee"), (0.85, "matcha"), (0.9, "water")]:
        store.add(Memory(MemoryType.PREFERENCE, content, subject="user", confidence=c))
    m = store.get(a.id)
    assert m.metadata["replace_count"] == 3
    assert len(m.metadata["replace_log"]) == 3


def test_log_capped_at_20():
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.PREFERENCE, "v0", subject="user", confidence=0.5))
    # 25 replaces, each strictly stronger than the last
    for i in range(1, 26):
        store.add(Memory(MemoryType.PREFERENCE, f"v{i}", subject="user",
                         confidence=0.5 + i * 0.01))
    m = store.get(a.id)
    assert m.metadata["replace_count"] == 25
    assert len(m.metadata["replace_log"]) == 20    # capped


def test_keep_both_does_not_touch_replace_log():
    store = InMemoryStore()
    a = store.add(Memory(MemoryType.FACT, "x1", subject="t"))   # KEEP_BOTH
    store.add(Memory(MemoryType.FACT, "x2", subject="t"))
    m = store.get(a.id)
    assert "replace_log" not in m.metadata

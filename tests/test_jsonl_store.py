from pathlib import Path

from typedmem import JSONLMemoryStore, Memory, MemoryType


def _seed(store):
    store.add(Memory(MemoryType.FACT, "x", subject="user"))
    store.add(Memory(MemoryType.PREFERENCE, "likes tea", subject="user", confidence=0.8))
    store.add(Memory(MemoryType.PREFERENCE, "likes coffee", subject="user", confidence=0.9))


def test_persists_across_reopen(tmp_path: Path):
    path = tmp_path / "m.jsonl"
    s1 = JSONLMemoryStore(path)
    _seed(s1)
    assert len(s1) == 2  # preference merged

    s2 = JSONLMemoryStore(path)
    assert len(s2) == 2
    prefs = s2.by_type(MemoryType.PREFERENCE)
    assert prefs and prefs[0].content == "likes coffee"


def test_delete_tombstone_survives_reopen(tmp_path: Path):
    path = tmp_path / "m.jsonl"
    s1 = JSONLMemoryStore(path)
    m = s1.add(Memory(MemoryType.EVENT, "went to park"))
    s1.delete(m.id)
    assert len(s1) == 0

    s2 = JSONLMemoryStore(path)
    assert len(s2) == 0


def test_compact_shrinks_file(tmp_path: Path):
    path = tmp_path / "m.jsonl"
    s = JSONLMemoryStore(path)
    for i in range(5):
        # Same subject preference → repeated updates produce many lines.
        s.add(Memory(MemoryType.PREFERENCE, f"v{i}", subject="user", confidence=0.5 + i * 0.05))
    pre = path.read_text().count("\n")
    s.compact()
    post = path.read_text().count("\n")
    assert post == 1 < pre

    s2 = JSONLMemoryStore(path)
    prefs = s2.by_type(MemoryType.PREFERENCE)
    assert len(prefs) == 1 and prefs[0].content == "v4"


def test_tolerates_corrupt_trailing_line(tmp_path: Path):
    path = tmp_path / "m.jsonl"
    s = JSONLMemoryStore(path)
    s.add(Memory(MemoryType.FACT, "good"))
    with path.open("a") as fh:
        fh.write("{not json")
    s2 = JSONLMemoryStore(path)
    assert len(s2) == 1

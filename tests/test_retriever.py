from datetime import timedelta

from typed_memory.retriever import Retriever
from typed_memory.schema import Memory, MemoryType, _now
from typed_memory import InMemoryStore as MemoryStore


def _seed():
    store = MemoryStore()
    store.add(Memory(MemoryType.FACT, "child born 2024", subject="child"))
    store.add(Memory(MemoryType.OBSERVATION, "said more milk", tags=["language"]))
    store.add(Memory(MemoryType.OBSERVATION, "tried to wear shoes", tags=["motor"]))
    store.add(Memory(MemoryType.GOAL, "learn to count to ten"))
    return store


def test_by_type():
    r = Retriever(_seed())
    assert len(r.by_type(MemoryType.OBSERVATION)) == 2


def test_by_tag():
    r = Retriever(_seed())
    assert len(r.by_tag("language")) == 1


def test_recent_orders_newest_first():
    store = MemoryStore()
    store.add(Memory(MemoryType.EVENT, "old", timestamp=_now() - timedelta(days=10)))
    store.add(Memory(MemoryType.EVENT, "new"))
    out = Retriever(store).recent()
    assert out[0].content == "new"


def test_relevant_finds_token_overlap():
    r = Retriever(_seed())
    hits = r.relevant("milk")
    assert hits
    assert "milk" in hits[0].memory.content


def test_relevant_filters_by_type():
    r = Retriever(_seed())
    hits = r.relevant("count", types=[MemoryType.GOAL])
    assert hits and hits[0].memory.type == MemoryType.GOAL

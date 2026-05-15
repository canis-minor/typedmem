from datetime import timedelta

from typedmem import (
    HashingEmbeddingProvider,
    InMemoryStore,
    Memory,
    MemoryType,
    Retriever,
)
from typedmem.schema import _now


def test_semantic_beats_token_overlap_on_paraphrase():
    """Semantic embedder should find paraphrases that token-overlap misses."""
    store = InMemoryStore()
    target = store.add(Memory(MemoryType.OBSERVATION, "child said more milk", tags=["language"]))
    store.add(Memory(MemoryType.OBSERVATION, "kitchen sink is leaking"))
    store.add(Memory(MemoryType.OBSERVATION, "weather is nice today"))

    retriever = Retriever(store, embedder=HashingEmbeddingProvider(dim=1024))
    hits = retriever.relevant("toddler asked for milk")
    assert hits[0].memory.id == target.id


def test_recency_breaks_ties():
    store = InMemoryStore()
    old = Memory(MemoryType.EVENT, "went to the park",
                 timestamp=_now() - timedelta(days=60))
    new = Memory(MemoryType.EVENT, "went to the park")
    store.add(old)
    store.add(new)

    retriever = Retriever(store, embedder=HashingEmbeddingProvider(dim=512))
    hits = retriever.relevant("went to the park")
    assert hits[0].memory.id == new.id


def test_type_filter():
    store = InMemoryStore()
    store.add(Memory(MemoryType.GOAL, "learn to count"))
    store.add(Memory(MemoryType.OBSERVATION, "learning to count today"))

    retriever = Retriever(store, embedder=HashingEmbeddingProvider())
    hits = retriever.relevant("counting", types=[MemoryType.GOAL])
    assert all(h.memory.type == MemoryType.GOAL for h in hits)


def test_falls_back_to_tokens_without_embedder():
    store = InMemoryStore()
    store.add(Memory(MemoryType.FACT, "the cat is on the mat"))
    retriever = Retriever(store)  # no embedder
    hits = retriever.relevant("cat")
    assert hits and "cat" in hits[0].memory.content

"""Demo from design doc §9: child development tracking.

Input: "Child said 'more milk' and tried to wear shoes"
Expected: language observation, motor skill observation, (and an emotional
event when present).
"""

from typed_memory import (
    HashingEmbeddingProvider,
    InMemoryStore,
    MemoryType,
    Retriever,
    RuleBasedExtractor,
)


def main() -> None:
    store = InMemoryStore()
    extractor = RuleBasedExtractor()
    retriever = Retriever(store, embedder=HashingEmbeddingProvider())

    transcripts = [
        ("2026-05-14 morning",  "Today the child said 'more milk' and tried to wear shoes."),
        ("2026-05-14 noon",     "She laughed when the dog barked and pointed at the window."),
        ("2026-05-15",          "Child loves bananas. We are trying to learn to count to ten."),
    ]

    for label, text in transcripts:
        for m in extractor.extract(text, subject="child"):
            store.add(m)
        print(f"[{label}] extracted; store size = {len(store)}")

    print("\n--- Observations by tag ---")
    for tag in ("language", "motor", "emotional", "cognitive"):
        items = retriever.by_tag(tag)
        if items:
            print(f"\n{tag.upper()} ({len(items)}):")
            for m in items:
                print(f"  - {m.content}  (conf={m.confidence:.2f})")

    print("\n--- All goals ---")
    for m in retriever.by_type(MemoryType.GOAL):
        print(f"  - {m.content}  [{m.status}]")

    print("\n--- All preferences ---")
    for m in retriever.by_type(MemoryType.PREFERENCE):
        print(f"  - {m.content}")

    print("\n--- Top relevant for 'shoes milk' ---")
    for hit in retriever.relevant("shoes milk", limit=5):
        print(f"  {hit.score:.2f}  [{hit.memory.type}] {hit.memory.content}")


if __name__ == "__main__":
    main()

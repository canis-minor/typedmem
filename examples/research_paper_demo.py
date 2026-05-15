"""Research-paper extraction demo using the ``research_paper`` profile.

Two papers independently support the same outcome. The REINFORCE policy on
``evidence`` merges their sources and lifts confidence, instead of storing
duplicate records.
"""

import json

from typed_memory import (
    DomainProfile,
    FakeClient,
    LLMExtractor,
    Retriever,
    SQLiteMemoryStore,
    Source,
)


# Simulated LLM responses for two papers extracting the same evidence.
PAPER_A_RESPONSE = json.dumps([
    {"type": "claim", "content": "Drug X reduces blood pressure",
     "confidence": 0.85, "subject": "drug_x",
     "source": {"document_id": "paper_a.pdf", "chunk_id": "intro"}},
    {"type": "method", "content": "Randomized controlled trial, n=120",
     "confidence": 0.9, "subject": "drug_x",
     "source": {"document_id": "paper_a.pdf", "chunk_id": "methods"}},
    {"type": "evidence", "content": "12mmHg systolic reduction",
     "confidence": 0.8, "subject": "drug_x",
     "source": {"document_id": "paper_a.pdf", "chunk_id": "results"}},
])

PAPER_B_RESPONSE = json.dumps([
    {"type": "evidence", "content": "Mean BP drop 10mmHg",
     "confidence": 0.75, "subject": "drug_x",
     "source": {"document_id": "paper_b.pdf", "chunk_id": "table_2"}},
    {"type": "limitation", "content": "Small sample size",
     "confidence": 0.9, "subject": "drug_x",
     "source": {"document_id": "paper_b.pdf", "chunk_id": "discussion"}},
])


def main() -> None:
    profile = DomainProfile.builtin("research_paper")
    print(f"Profile: {profile.name}")
    print(f"  Types: {sorted(profile.all_types())}\n")

    client = FakeClient([PAPER_A_RESPONSE, PAPER_B_RESPONSE])
    extractor = LLMExtractor(client, profile=profile)
    store = SQLiteMemoryStore.for_profile(profile, path=":memory:")

    print("── Paper A ───")
    for m in extractor.extract("[paper A full text]"):
        store.add(m)
        print(f"  [{m.type}] {m.content}  ({m.sources[0].document_id})")

    print("\n── Paper B ───")
    for m in extractor.extract("[paper B full text]"):
        store.add(m)
        print(f"  [{m.type}] {m.content}  ({m.sources[0].document_id})")

    print("\n── Stored evidence (REINFORCE merges both papers) ───")
    for ev in store.by_type("evidence"):
        sources = ", ".join(s.document_id for s in ev.sources)
        print(f"  conf={ev.confidence:.2f}  content={ev.content!r}")
        print(f"  sources: {sources}")

    print("\n── Retrieval ───")
    from typed_memory import HashingEmbeddingProvider
    r = Retriever(store, embedder=HashingEmbeddingProvider())
    for hit in r.relevant("blood pressure drop"):
        print(f"  {hit.score:.2f}  [{hit.memory.type}] {hit.memory.content}")

    store.close()


if __name__ == "__main__":
    main()

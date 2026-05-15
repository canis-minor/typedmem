"""TypedMemory for an engineering design agent.

A small story:

  1. An agent reads through design-discussion snippets.
  2. It extracts decisions, constraints, and risks using the
     ``engineering_design`` profile.
  3. A later snippet revises the storage decision — SUPERSEDE preserves
     the audit trail.
  4. Two snippets express contradicting constraints — FLAG cross-links them.
  5. The agent runs Evolvers to surface contradictions and inspect history.

No real LLM is required; ``FakeClient`` returns pre-canned extraction JSON so
the script runs offline. Swap in ``AnthropicClient`` or ``OpenAIClient`` to
extract from real text.
"""

import json

from typed_memory import (
    ContradictionSurfacer,
    DomainProfile,
    FakeClient,
    LLMExtractor,
    Memory,
    SQLiteMemoryStore,
    Source,
)


# ── Pretend an LLM extracted each of these snippets ──────────────────────────
SNIPPET_1 = json.dumps([
    {"type": "decision", "content": "Use SQLite for memory storage",
     "confidence": 0.9, "subject": "storage_backend",
     "source": {"document_id": "design_v1.md", "chunk_id": "storage"}},
    {"type": "constraint", "content": "Memory store must persist between processes",
     "confidence": 0.95, "subject": "storage_backend",
     "source": {"document_id": "design_v1.md", "chunk_id": "requirements"}},
    {"type": "risk", "content": "SQLite is single-writer; concurrent writes may block",
     "confidence": 0.8, "subject": "storage_backend",
     "source": {"document_id": "design_v1.md", "chunk_id": "risks"}},
])

SNIPPET_2 = json.dumps([
    {"type": "decision", "content": "Switch to PostgreSQL for concurrent multi-agent writes",
     "confidence": 0.9, "subject": "storage_backend",
     "source": {"document_id": "design_v2.md", "chunk_id": "revision"}},
    {"type": "constraint", "content": "Memory store must support concurrent writers",
     "confidence": 0.95, "subject": "storage_backend",
     "source": {"document_id": "design_v2.md", "chunk_id": "requirements"}},
])

SNIPPET_3 = json.dumps([
    # A contradiction with the SQLite constraint above.
    {"type": "constraint", "content": "Storage must run with zero external services",
     "confidence": 0.95, "subject": "storage_backend",
     "source": {"document_id": "constraints.md", "chunk_id": "ops"}},
    {"type": "risk", "content": "Running Postgres adds an external service",
     "confidence": 0.85, "subject": "storage_backend",
     "source": {"document_id": "constraints.md", "chunk_id": "ops"}},
])


def header(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


def main() -> None:
    profile = DomainProfile.builtin("engineering_design")
    print(f"profile: {profile.name}")
    print(f"types:   {sorted(profile.all_types())}")

    store = SQLiteMemoryStore.for_profile(profile, path=":memory:")
    extractor = LLMExtractor(
        client=FakeClient([SNIPPET_1, SNIPPET_2, SNIPPET_3]),
        profile=profile,
    )

    header("Snippet 1 — initial design")
    for m in extractor.extract("design_v1.md text"):
        store.add(m)
        print(f"  + [{m.type}] {m.content}")

    header("Snippet 2 — revised storage decision")
    for m in extractor.extract("design_v2.md text"):
        store.add(m)
        # SUPERSEDE on decision flips the previous one; constraint REPLACES.
        marker = "↻ supersede" if m.type == "decision" else "+"
        print(f"  {marker} [{m.type}] {m.content}")

    header("Snippet 3 — operational constraint contradicts")
    for m in extractor.extract("constraints.md text"):
        store.add(m)
        print(f"  + [{m.type}] {m.content}")

    header("Active decisions (superseded hidden)")
    for m in store.by_type("decision"):
        print(f"  conf={m.confidence:.2f}  {m.content}")

    header("All decisions including history")
    for m in store.by_type("decision", include_superseded=True):
        tag = " (superseded)" if m.superseded_by else ""
        print(f"  {m.content}{tag}")

    header("Contradictions surfaced by evolver")
    contradictions = store.contradictions()
    if not contradictions:
        print("  (none — FLAG is for constraints by default, requires distinct slots)")
    else:
        for cluster in contradictions:
            print(f"  cluster of {len(cluster)}:")
            for m in cluster:
                print(f"    [{m.type}] {m.content}")

    header("Risks accumulated for this design")
    for m in store.by_type("risk"):
        src = m.sources[0].document_id if m.sources else "?"
        print(f"  [{src}] {m.content}")

    header("Lifecycle of the storage decision")
    decisions = store.by_type("decision", include_superseded=True)
    decisions_by_id = {m.id: m for m in decisions}
    superseded = [m for m in decisions if m.superseded_by]
    for m in superseded:
        successor = decisions_by_id.get(m.superseded_by)
        print(f"  {m.timestamp.date()}  {m.content}")
        print(f"      ↳ superseded by: {successor.content if successor else m.superseded_by}")
    active = [m for m in decisions if not m.superseded_by]
    for m in active:
        srcs = ", ".join(s.document_id for s in m.sources) or "(none)"
        print(f"  {m.timestamp.date()}  {m.content}  ← {srcs}  [ACTIVE]")

    header("Source provenance on every memory")
    for m in store.all(include_superseded=True):
        srcs = ", ".join(s.document_id for s in m.sources) or "(none)"
        print(f"  [{m.type:<11}] {m.content[:55]:<55} ← {srcs}")

    store.close()


if __name__ == "__main__":
    main()

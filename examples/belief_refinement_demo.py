"""Belief refinement over time — what v0.6's timeline gives you.

An agent's understanding of a user gets more *specific* across conversations.
With TypedMemory v0.6, you don't just see the final belief — you see the
journey.

This is the canonical v0.6 use case: not flip-flop ("SQLite → Postgres →
SQLite"), but refinement ("pytest" → "pytest + parametrize" → "...real DB
for integration" → "...fakes not mocks for unit"). The agent's belief gets
sharper each conversation; the timeline shows why.

Run: python examples/belief_refinement_demo.py
"""

from datetime import datetime, timezone

from typedmem import InMemoryStore, Memory, MemoryType


def section(title: str) -> None:
    print(f"\n══ {title} " + "═" * max(0, 60 - len(title)))


store = InMemoryStore()

# Four conversations refining the same belief slot
# (workspace=default, type=preference, subject=testing_approach).
# The default policy has preference→REPLACE — each new statement updates
# the existing memory in place. The event log captures every refinement.
CONVERSATIONS = [
    ("day_1",  "pytest"),
    ("day_5",  "pytest with parametrize for table-driven tests"),
    ("day_10", "pytest with parametrize; integration tests must hit a real DB"),
    ("day_14", "pytest with parametrize; real DB for integration; fakes (not mocks) for unit"),
]

section("Simulating four conversations")
for day, content in CONVERSATIONS:
    print(f"  [{day}]  user says: {content!r}")
    store.add(
        Memory(MemoryType.PREFERENCE, content,
               subject="testing_approach", confidence=0.9),
        event_source="agent",
        event_source_name=f"conversation:{day}",
    )

# What does the agent believe right now?
section("Current belief")
current = store.by_type(MemoryType.PREFERENCE)[0]
print(f"  {current.content}")
print(f"  (confidence {current.confidence:.2f})")

# How did it get there? `store.history(memory_id)` returns every event
# that touched this memory, oldest first.
section("Timeline")
print(f"  {'action':<10}  {'source':<8}  {'source_name':<24}  reason")
print("  " + "─" * 90)
for e in store.history(current.id):
    reason = e.reason[:50] + "…" if len(e.reason) > 50 else e.reason
    print(f"  {e.action:<10}  {e.source:<8}  {(e.source_name or ''):<24}  {reason}")

# The same data, but as the canonical change feed since some past timestamp.
# This is what a downstream sync consumer would pull periodically.
section("changed_since() — the canonical change feed")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
events = store.changed_since(EPOCH)
print(f"  {len(events)} event(s) since {EPOCH:%Y-%m-%d}:")
for e in events:
    print(f"    {e.timestamp:%H:%M:%S.%f}  {e.action:<10}  via {e.source_name}")
print()
print("  In a real deployment, you'd pass a real cutoff (e.g. 'last sync time')")
print("  and ship these to your downstream system — adds, replaces, deletes,")
print("  and evolver actions all flow through this single feed.")

# v0.4.2-compatible API is still there, backed by the same event log:
section("Backwards-compat: store.evolution_history()")
hist = store.evolution_history(current.id)
print(f"  {len(hist)} entries, dict-shaped (pre-v0.6 API still works):")
for h in hist[:2]:
    print(f"    {h}")
if len(hist) > 2:
    print(f"    ... and {len(hist) - 2} more")

"""v0.4c demo: contradiction surfacing, drift detection, goal resolution, and
non-destructive summarization — all on a single InMemoryStore.

Uses FakeClient so the script runs offline. Swap in OpenAIClient or
AnthropicClient for real LLM summarization.
"""

from datetime import timedelta

from typedmem import (
    ConflictPolicy,
    ContradictionSurfacer,
    FakeClient,
    GoalResolver,
    HashingEmbeddingProvider,
    InMemoryStore,
    Memory,
    MemoryType,
    PolicyEngine,
    PreferenceDriftDetector,
    SummaryEvolver,
    TypePolicy,
    revert_goal_resolution,
)
from typedmem.policy import DEFAULT_POLICIES
from typedmem.schema import _now


def _engine_with_flag():
    pols = dict(DEFAULT_POLICIES)
    pols["fact"] = TypePolicy(None, False, ConflictPolicy.FLAG)
    return PolicyEngine(pols)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * (50 - len(title)))


def main() -> None:
    store = InMemoryStore(_engine_with_flag())

    # ── 1. seed contradictions ────────────────────────────────────────
    store.add(Memory(MemoryType.FACT, "Lives in California", subject="user_42"))
    store.add(Memory(MemoryType.FACT, "Lives in New York",   subject="user_42"))

    # ── 2. seed preference drift ──────────────────────────────────────
    store.add(Memory(MemoryType.PREFERENCE, "likes tea",     subject="user_42", confidence=0.5))
    for content, c in [("likes coffee", 0.55), ("likes matcha", 0.6),
                       ("likes water", 0.65), ("likes juice", 0.7)]:
        store.add(Memory(MemoryType.PREFERENCE, content, subject="user_42", confidence=c))

    # ── 3. seed goal + matching event ─────────────────────────────────
    store.add(Memory(MemoryType.GOAL, "learn to count to ten", subject="child"))
    store.add(Memory(MemoryType.EVENT, "child counted up to ten today", subject="child"))

    # ── 4. seed stale event cluster ───────────────────────────────────
    old = _now() - timedelta(days=180)
    for i in range(4):
        store.add(Memory(
            MemoryType.EVENT, f"baby babbled new sound #{i}", subject="child",
            confidence=0.6, timestamp=old,
        ))

    section("Contradictions")
    for cluster in ContradictionSurfacer().clusters(store):
        print(f"  cluster of {len(cluster)}:")
        for m in cluster:
            print(f"    [{m.type}] {m.content}")

    section("Preference drift")
    drift = PreferenceDriftDetector(min_replaces=3).evolve(store)
    print(drift.summary())
    for r in drift.records:
        print(f"  {r.reason}")

    section("Goal resolution (dry-run)")
    embedder = HashingEmbeddingProvider(dim=1024)
    dry = GoalResolver(embedder, threshold=0.2).evolve(store, dry_run=True)
    print(dry.summary())
    for r in dry.records:
        print(f"  {r.reason}")

    section("Goal resolution (commit)")
    committed = GoalResolver(embedder, threshold=0.2).evolve(store)
    print(committed.summary())
    for r in committed.records:
        goal = store.get(r.output_ids[0])
        print(f"  goal[{goal.subject}] '{goal.content}' → status={goal.status}")

    section("Revert the resolution")
    for r in committed.records:
        revert_goal_resolution(store, r.output_ids[0])
        goal = store.get(r.output_ids[0])
        print(f"  goal[{goal.subject}] reverted to status={goal.status}")

    section("Non-destructive summarization")
    fake = FakeClient("Child made multiple early vocalizations during this period.")
    summary_result = SummaryEvolver(fake, min_cluster_size=3).evolve(store)
    print(summary_result.summary())
    for r in summary_result.records:
        new_id = r.output_ids[0] if r.output_ids else None
        if new_id:
            summary = store.get(new_id)
            print(f"  summary: {summary.content!r}")
            print(f"  links back to {len(summary.metadata['summarizes'])} originals")

    section("Originals are untouched")
    babble_events = [m for m in store if "babbled" in m.content]
    assert all(m.superseded_by is None for m in babble_events)
    print(f"  {len(babble_events)} babbling events still present, none superseded")

    section("Audit trail on the goal we resolved + reverted")
    for r in committed.records:
        history = store.evolution_history(r.output_ids[0])
        for entry in history:
            print(f"  {entry['action']}: {entry['reason']}")


if __name__ == "__main__":
    main()

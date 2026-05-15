# Evolvers

Evolvers read stored memories — symmetric to `Extractor`, which reads text — and produce a list of audited actions. Every action is recorded in an `EvolutionRecord` (returned to the caller) and appended to each affected memory's `metadata["evolution_history"]` (cap of 50 entries).

```python
from typedmem import (
    ContradictionSurfacer, PreferenceDriftDetector,
    GoalResolver, SummaryEvolver,
)
```

## The protocol

```python
class Evolver(Protocol):
    name: str
    def evolve(
        self,
        store: MemoryStore,
        *,
        workspace: str | None = None,
        dry_run: bool = False,
    ) -> EvolutionResult: ...
```

Returns:

```python
@dataclass
class EvolutionRecord:
    evolver: str          # which Evolver
    action: str           # flag | annotate | create | resolve | supersede | revert
    input_ids: list[str]  # memories that triggered the action
    output_ids: list[str] # memories created or modified
    reason: str
    timestamp: datetime

@dataclass
class EvolutionResult:
    evolver: str
    records: list[EvolutionRecord]
    dry_run: bool
```

## ContradictionSurfacer

Pure read. Walks the FLAG-generated `metadata["conflicts_with"]` graph and returns connected components of two or more memories.

```python
from typedmem import ContradictionSurfacer

result = ContradictionSurfacer().evolve(store)
for record in result.records:
    print(record.input_ids)

# or the convenience helper on the store:
for cluster in store.contradictions():
    for m in cluster:
        print(m.content)
```

`dry_run` is irrelevant — this evolver never mutates.

## PreferenceDriftDetector

Catches unstable preferences via the `metadata["replace_log"]` that REPLACE writes on every conflict resolution. Annotates the memory with a `drift_flags` entry; does not delete or restructure.

```python
from typedmem import PreferenceDriftDetector

result = PreferenceDriftDetector(
    min_replaces=3,
    window_days=30,
    types=None,                # None = any type with replace_log
).evolve(store)
```

Reads after a run:

```python
unstable = store.drift_flags(workspace="user_42")
```

## GoalResolver

Matches active goals against recent evidence using a semantic embedder. Strict by default (threshold 0.85). Preserves `previous_status` and `resolved_by` so resolution is one-level reversible.

```python
from typedmem import GoalResolver, HashingEmbeddingProvider, revert_goal_resolution

embedder = HashingEmbeddingProvider()

# Always preview first.
plan = GoalResolver(embedder, threshold=0.85).evolve(store, dry_run=True)
print(plan.summary())

# Commit.
GoalResolver(embedder, threshold=0.85).evolve(store)

# Undo a misfire.
revert_goal_resolution(store, goal_id)
```

`evidence_types` defaults to `("event", "outcome", "finding")` — the set of types that "could resolve" an active goal. Override per-domain.

## SummaryEvolver

**Non-destructive in v0.4.** Clusters stale memories sharing `(workspace, type, subject)`, asks an LLMClient for one condensed sentence, creates a new memory of `target_type` (default `"fact"`) that links back via `metadata["summarizes"]`. Originals are tagged with `metadata["summarized_by"]` so they don't get clustered again, but they're **never deleted, modified, or superseded**. Destructive compaction is planned for v0.5.

```python
from typedmem import SummaryEvolver, AnthropicClient

SummaryEvolver(
    client=AnthropicClient(),                   # needs [anthropic] extra
    confidence_floor=0.3,                       # decayed conf below this counts as stale
    min_cluster_size=3,
    target_type="fact",                         # type of the new summary memory
    cluster_types=("event", "observation"),     # which types are eligible
).evolve(store)
```

Use `FakeClient` to dry-test the clustering / prompt without an API key:

```python
from typedmem import FakeClient
SummaryEvolver(FakeClient("..."), min_cluster_size=3).evolve(store)
```

## Audit trail

Every mutating evolver writes an `EvolutionRecord` into `metadata["evolution_history"]` of each affected memory. Read it back with the store helper or the CLI.

```python
for entry in store.evolution_history(memory_id):
    print(entry["action"], entry["reason"], entry["timestamp"])
```

```bash
typedmem history MEMORY_ID
```

## Safety stance

| Evolver | Mutates? | Safe-by-default? |
|---|---|---|
| `ContradictionSurfacer` | No | N/A |
| `PreferenceDriftDetector` | Annotation only (additive metadata) | Reversible by deleting `drift_flags` |
| `GoalResolver` | Sets `status`, writes `previous_status` | Reversible via `revert_goal_resolution()`; `dry_run` parameter |
| `SummaryEvolver` | Creates new memory; tags originals with `summarized_by` | Originals untouched; new memory deletable |

The CLI defaults destructive evolvers to `--dry-run`; you opt in to mutation with `--apply`.

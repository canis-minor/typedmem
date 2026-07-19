> This repository is part of the **[Reliable Long-Running Agents (RLRA)](https://github.com/canis-minor)** research initiative.

# TypedMemory

**Contract-driven memory for AI agents.**
*Typed schemas. Explicit conflict policies. Structured provenance. Typed event timeline.*

[![CI](https://github.com/canis-minor/typedmem/actions/workflows/ci.yml/badge.svg)](https://github.com/canis-minor/typedmem/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/typedmem.svg)](https://pypi.org/project/typedmem/)
[![Python](https://img.shields.io/pypi/pyversions/typedmem.svg)](https://pypi.org/project/typedmem/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

📦 [PyPI](https://pypi.org/project/typedmem/) · 📚 [Docs](https://canis-minor.github.io/typedmem/) · 🏷️ [Releases](https://github.com/canis-minor/typedmem/releases) · 📝 [Changelog](CHANGELOG.md)

## TL;DR

**Memory you can contract against.** Four explicit contracts make TypedMemory:

- **`DomainProfile`** — typed schema; invalid writes are *rejected*, not "learned"
- **`ConflictPolicy`** — declarative behaviour on slot collision (`REPLACE` / `SUPERSEDE` / `REINFORCE` / `FLAG` / `KEEP_BOTH` / `IGNORE`)
- **`Source`** — structured provenance with `(document_id, chunk_id, span)` dedup identity
- **`MemoryEvent`** — first-class typed change feed (`history` / `timeline` / `changed_since`)

Built for domain apps where *"the memory accepted nonsense"* is a correctness bug.

## The problem

AI agents start believing their own hallucinations. They:

- **contradict themselves silently** — the last write wins, the conflict disappears
- **overwrite past decisions with no audit trail** — you can't debug what you can't see
- **never resolve goals** — yesterday's "I'll do X" looks identical to today's "I did X"

TypedMemory makes that visible.

## The contradiction-detection moment

```bash
$ pip install typedmem

$ typedmem --profile engineering_design add \
    "SQLite handles our single-writer load fine" --type risk --subject storage
$ typedmem --profile engineering_design add \
    "SQLite blocks under concurrent writes"     --type risk --subject storage

$ typedmem --profile engineering_design contradictions

1 contradiction cluster(s):

cluster 1 (2 memories):
  [risk] [storage] SQLite handles our load fine
  [risk] [storage] SQLite blocks under concurrent writes
```

Two memories cross-linked by the FLAG policy. Both still in the store — no silent overwrite. Run `typedmem history <id>` on either to see exactly when and why the state changed.

## 5 lines for an agent

```python
from typedmem import AgentMemory

mem = AgentMemory(profile="personal", path="agent.db")

mem.remember("User wants to learn Rust by year end")
mem.remember("User lives in Tokyo")

hits = mem.recall("what is the user trying to learn?")
#   → [ScoredMemory(content="User wants to learn Rust...", score=0.78)]

report = mem.reflect()
#   → AgentMemoryReflection(contradictions=[], drift_records=[], ...)
```

Four verbs over the whole pipeline: **`remember`** (extract + store), **`recall`** (semantic retrieval), **`reflect`** (run the evolver pipeline), **`forget`** (explicit delete).

**More demos:** [`examples/DEMO.md`](examples/DEMO.md) for the 30-second no-flags paste · [`examples/agent_loop_demo.py`](examples/agent_loop_demo.py) for the before-vs-after agent story.

## Before vs After

| | Without TypedMemory | With TypedMemory |
|---|---|---|
| **Agent changes its mind** | Last write silently overwrites | REPLACE policy + `PreferenceDriftDetector` flag instability; the change is recorded in the event log |
| **Two facts contradict** | One overwrites the other; you'll never know | FLAG cross-links both; `typedmem contradictions` surfaces the cluster |
| **A decision gets revised** | Old decision lost | SUPERSEDE keeps the audit trail (`old.superseded_by → new.id`); `typedmem history` shows the lifecycle |
| **"How did the agent's view evolve?"** | You've lost it | `store.timeline(subject="storage_backend")` returns every change with source, reason, and timestamp |
| **Goals accumulate** | They sit there forever, mixing with current intent | `GoalResolver` matches incoming events to active goals and flips them to `resolved` |
| **Same fact arrives from 3 sources** | 3 duplicate memories | REINFORCE merges into one, unions sources by `(document_id, chunk_id, span)`, boosts confidence |
| **Stale events pile up** | Search noise grows | `SummaryEvolver` condenses non-destructively; originals link forward via `metadata["summarizes"]` |

## The four contracts

Most memory systems are **learned** — they consolidate, refine, and optimize for retrieval recall. TypedMemory is **contracted** — every state change is governed by rules you declare up front.

- **Schema is a contract.** `DomainProfile` + `TypeSpec` declare which memory types exist, what fields they require, and what tags they allow. Writes that don't match are **rejected** (HTTP 422 from the server). The system does not "learn around" your schema.
- **Behaviour is a contract.** Each type declares a `ConflictPolicy` — what should happen when a new memory hits the same `(workspace, type, subject)` slot. `REPLACE` overwrites and logs. `SUPERSEDE` keeps both with a forward link. `REINFORCE` merges sources and bumps confidence. `FLAG` cross-links contradictions instead of silently picking a winner. Policies are declarative, deterministic, and yours.
- **Provenance is a contract.** Every memory carries `Source(document_id, chunk_id, span, authority)` — not optional metadata, but the dedup identity used by REINFORCE. Three sources backing the same fact merge into one memory with three sources, not three duplicates.
- **Evolution is a contract.** Every successful add / update / delete / conflict / evolver action emits a typed `MemoryEvent` to an indexed log. `store.history(id)` answers *"how did this memory change?"*. `store.timeline(subject=…, source=…)` filters across the log. `store.changed_since(t)` is the canonical change feed for sync consumers.

The agent's beliefs are auditable because the contracts are explicit. The whole point: when the memory got something wrong, you can prove *what* changed, *when*, *why*, and *who* did it.

## What TypedMemory is **not**

TypedMemory is intentionally narrow:

- **Not a general-purpose retrieval engine.** We don't compete on benchmark recall. If retrieval quality is your bottleneck, you're in the wrong place.
- **Not a hosted memory cloud.** The v0.7 server is BYO-deploy: Cloud Run, Docker, systemd — your hosting choice.
- **Not a plug-and-play layer for agent frameworks.** We don't ship LangChain / CrewAI / AutoGen adapters. The wire format is REST + JSON; bring your own integration.
- **Not a "memory that learns" black box.** No implicit consolidation, no learned dedup, no opaque merging. Every state change goes through a `ConflictPolicy` you declared.

If those omissions sound like features to you, you're the audience.

## Use cases

**Primary:**

- **Debugging hallucinating agents.** When an agent flips its story, run `typedmem history <id>` and see every state change with reason, timestamp, and previous content. Contradictions surface via `mem.reflect()` instead of disappearing under the next write.
- **Long-term agent memory** — preferences, goals, drift. `mem.remember()` captures each session's signal. `mem.recall()` lets the next session see the current state. `mem.reflect()` catches preferences that keep flipping and goals that match recent events.

**Also good for:**

- Multi-document research / RAG with structured provenance — `Source(document_id, chunk_id, span, authority)` per memory; REINFORCE merges duplicates across papers
- Design-doc agents — decisions SUPERSEDE rather than overwriting; full audit trail
- Multi-tenant agents (legal + medical + customer-success on one machine) — `workspace` isolates each domain

## How it works

```
                              ┌──────────────────┐
                              │  DomainProfile   │  ← schema: which types,
                              │  TypeSpec × N    │     which policies,
                              │  prompt + rules  │     which validations
                              └────────┬─────────┘
                                       │
       text ──► Extractor ──► Memory ──┴──► MemoryStore ──► Retriever
                                            │
                                            ▼
                                         Evolver
                              (contradictions, drift, goals,
                               non-destructive summarization)
```

Every memory has a **type** (claim, decision, observation, …), a **confidence**, a **structured source**, a **lifecycle policy**, and a **workspace** — not a string in a vector database. Memories know how to update themselves on conflict, how to decay over time, and how to be summarized.

**Zero runtime dependencies.** Stdlib only. LLM clients, YAML profile loading, and richer embedders are optional extras.

## Why this exists

Most "AI memory" libraries are wrappers around a vector database. That works for "remember what the user said," but it falls apart the moment you want an agent to:

- track **who said what, in which document, at which span** (provenance)
- handle **the same fact from three sources** without storing it three times (reinforcement)
- recognize that **a new decision supersedes the old one** without losing the audit trail
- **summarize stale events** without throwing away the originals
- **isolate** legal memory from medical memory on the same machine
- **flag contradictions** instead of silently overwriting them

TypedMemory handles these as first-class concepts, not bolt-ons.

## Install

```bash
pip install typedmem                       # default install, zero deps
pip install 'typedmem[anthropic]'          # + AnthropicClient
pip install 'typedmem[openai]'             # + OpenAIClient
pip install 'typedmem[yaml]'               # + DomainProfile.from_yaml()
pip install 'typedmem[server]'             # + HTTP server (FastAPI + uvicorn)
pip install 'typedmem[gcp]'                # + Cloud Run / Google ID-token auth
pip install 'typedmem[all]'
```

Python 3.10+.

## Run as a service (v0.7+)

Not a Python project? Use typedmem over HTTP:

```bash
pip install 'typedmem[server]'
typedmem --store agent.db serve --api-token $(openssl rand -hex 32)
```

REST API under `/v1/`, interactive docs at `/docs`. Same surface as the
Python library — `add`, `get`, `delete`, `list`, `recall`, `history`,
`timeline`, `changed-since`, `reflect`. Works on Cloud Run + GCS FUSE,
plain Docker, or systemd. Full deploy guide: [`docs/server.md`](docs/server.md).

## 60-second demo: an engineering design agent

```python
import json
from typedmem import (
    DomainProfile, FakeClient, LLMExtractor, SQLiteMemoryStore,
)

profile = DomainProfile.builtin("engineering_design")
store = SQLiteMemoryStore.for_profile(profile, "design.db")

# Pretend the LLM extracted these from your design docs.
extractor = LLMExtractor(client=FakeClient([
    json.dumps([
        {"type": "decision", "content": "Use SQLite for storage",
         "subject": "storage_backend", "confidence": 0.9,
         "source": {"document_id": "design_v1.md"}},
        {"type": "risk", "content": "SQLite is single-writer",
         "subject": "storage_backend", "confidence": 0.8,
         "source": {"document_id": "design_v1.md"}},
    ]),
    json.dumps([
        {"type": "decision", "content": "Switch to PostgreSQL for concurrent writes",
         "subject": "storage_backend", "confidence": 0.9,
         "source": {"document_id": "design_v2.md"}},
        {"type": "risk", "content": "Postgres adds an external service",
         "subject": "storage_backend", "confidence": 0.85,
         "source": {"document_id": "design_v2.md"}},
    ]),
]), profile=profile)

for snippet in ("v1 text", "v2 text"):
    for m in extractor.extract(snippet):
        store.add(m)

# decision → SUPERSEDE: old preserved, new active.
print(store.by_type("decision"))                       # → just PostgreSQL
print(store.by_type("decision", include_superseded=True))  # → both

# risk → FLAG: two risks on the same subject get cross-linked.
for cluster in store.contradictions():
    for m in cluster:
        print(m.content)                                # → both risks
```

See [`examples/engineering_design_demo.py`](examples/engineering_design_demo.py) for the full version with audit trail and source provenance, or run:

```bash
typedmem profiles
typedmem --profile engineering_design add "..." --document-id design_v3.md
typedmem --profile engineering_design list --type decision
typedmem evolve --evolver contradictions
```

## The mental model

| Layer | What it gives you | Examples |
|---|---|---|
| **`Memory`** | Typed object with content + confidence + workspace + sources + status | `Memory(type="claim", content=..., sources=[Source(...)])` |
| **`Source`** | Structured provenance with hashable identity | `(document_id, chunk_id, span)` — dedup key for REINFORCE |
| **`workspace`** | Namespace on every memory | One agent, multiple corpora, zero cross-contamination |
| **`ConflictPolicy`** | What to do when a new memory hits the same `(workspace, type, subject)` slot | `REPLACE` · `KEEP_BOTH` · `SUPERSEDE` · `REINFORCE` · `FLAG` · `IGNORE` |
| **`DomainProfile`** | Schema for a domain: which types, what policy each obeys, what's required | `engineering_design` · `research_paper` · `legal` · `medical_literature` · `personal` · … |
| **`Evolver`** | Reads memories (not text); produces audit-trailed actions | `ContradictionSurfacer` · `PreferenceDriftDetector` · `GoalResolver` · `SummaryEvolver` |

## Built-in profiles

| Profile | Types | Notable policies |
|---|---|---|
| `core` | fact, note, goal, task, event | Shared primitives all other profiles can opt into |
| `personal` | + preference, observation | `preference → REPLACE (60d decay)` |
| `child_development` | + observation (tagged), milestone, concern | observation tags: language/motor/emotional/cognitive/social |
| `research_paper` | + claim, method, evidence, limitation, open_question | **evidence → REINFORCE** (multiple papers corroborate) |
| `engineering_design` | + decision, constraint, risk, assumption, todo | **decision → SUPERSEDE**, **risk → FLAG** |
| `legal` | + obligation, exception, deadline, definition, citation | **definition → SUPERSEDE** |
| `medical_literature` | + finding, population, intervention, outcome, limitation | **outcome → REINFORCE** across studies |

Custom profiles via Python dataclass, JSON, or YAML.

## Storage

Three backends, one ABC:

| Store | Persistence | Notes |
|---|---|---|
| `InMemoryStore` | None | Default; fastest |
| `JSONLMemoryStore` | Append-only file | Last-write-wins; tombstones; `compact()` rewrites |
| `SQLiteMemoryStore` | SQLite file | Indexed on `(workspace, type, subject)`; persists embeddings; v0.6 adds a `memory_events` table (timeline); schema auto-migrates from v0.2+ |

```python
from typedmem import SQLiteMemoryStore, DomainProfile

store = SQLiteMemoryStore.for_profile(
    DomainProfile.builtin("research_paper"),
    path="papers.db",
)
```

## Retrieval

```python
from typedmem import HashingEmbeddingProvider, Retriever

retriever = Retriever(store, embedder=HashingEmbeddingProvider())
hits = retriever.relevant(
    "blood pressure reduction",
    types=["evidence"],
    workspace="cardiology",
)
```

`relevant()` blends three signals: `semantic` (cosine), `recency` (exponential decay), `confidence` (with type-specific half-life). Without an embedder, falls back to token overlap.

## Timeline (v0.6)

Retrieval answers *"what's true now?"*. The timeline answers *"how did we get here?"*. Every successful add / update / delete / conflict-resolution / evolver action emits a typed `MemoryEvent` into an indexed event log.

```python
from datetime import datetime, timedelta, timezone

mem.remember("User prefers dark mode")
mem.remember("Actually, light mode in the morning")

# Everything that ever touched this memory:
mid = mem.recall("color theme")[0].memory.id
for e in mem.store.history(mid):
    print(f"{e.timestamp:%H:%M:%S}  {e.source}/{e.source_name}  {e.action}")
#   23:58:32  agent/AgentMemory.remember  added
#   23:58:33  agent/AgentMemory.remember  replaced

# Or filter by subject / type / workspace / source:
mem.store.timeline(subject="storage_backend", source="evolver")

# Or pull the canonical change feed since a point in time
# (for sync, replication, downstream notification):
since = datetime.now(timezone.utc) - timedelta(minutes=10)
for e in mem.store.changed_since(since):
    ship_to_downstream(e)
```

Each event carries `memory_id`, `workspace`, `type`, `subject`, `action`, `source` (one of `"store"` / `"evolver"` / `"agent"` / `"user"` / `"system"`), `source_name`, `reason`, `input_ids`, `output_ids`, `payload`, `timestamp`. Delete events outlive the memory row — `changed_since()` surfaces deletions to consumers staying in sync.

## Evolution

Evolvers read stored memories and produce auditable actions.

```python
from typedmem import (
    ContradictionSurfacer, PreferenceDriftDetector,
    GoalResolver, SummaryEvolver,
    HashingEmbeddingProvider, AnthropicClient,
)

# 1. Pure read: walk the FLAG graph.
for cluster in store.contradictions():
    print(f"{len(cluster)} memories cross-link as contradictions")

# 2. Annotation: catch unstable preferences.
PreferenceDriftDetector(min_replaces=3, window_days=30).evolve(store)

# 3. Safe match: dry-run first, then commit.
embedder = HashingEmbeddingProvider()
plan = GoalResolver(embedder, threshold=0.85).evolve(store, dry_run=True)
print(plan.summary())
GoalResolver(embedder, threshold=0.85).evolve(store)            # commit

# 4. Non-destructive summary of stale events.
SummaryEvolver(AnthropicClient(), min_cluster_size=3).evolve(store)
# Originals untouched; new memory links via metadata["summarizes"].
```

Every action emits a typed `MemoryEvent` into the store's indexed event log — `source="evolver"`, `source_name="goal_resolver"` (etc.), plus `action`, `input_ids`, `output_ids`, `reason`, `timestamp`. Query with `store.history(memory_id)`, `store.timeline(subject=..., source="evolver")`, or `store.changed_since(t)`. No black-box mutations, no `metadata["evolution_history"]` cap to worry about.

## Kernel (v0.8) — governed state transitions

Under the hood, **every** mutation now goes through one funnel. A `Transition` is an inert description of intent; the `TransitionEngine` is the only thing that writes to storage — it validates, resolves conflicts, bumps a persisted `version`, emits the event, and persists. Store `add`/`delete`, conflict resolution, and all three evolvers route through it.

```python
from typedmem import Transition

# Optimistic concurrency: refuse to clobber a newer state.
store.apply_transition(Transition(
    action="update", memory_id=goal.id, expected_version=goal.version,
    changes={"status": "resolved"}, actor="evolver", actor_name="goal_resolver",
))
# → ConcurrencyError if goal.version has moved; LifecycleError on an illegal status
```

Behavior is injectable via three strategies, each with a default that preserves prior behavior: `IdentityStrategy` (slot/dedup key), `ConfidenceStrategy` (reinforcement + decay), `LifecycleStrategy` (status validation + `is_active`). Public API — all importable from `typedmem`: `Transition`, `TransitionEngine`, `TransitionResult`, `ConcurrencyError`, `LifecycleError`, `IdentityStrategy` / `SlotIdentityStrategy`, `ConfidenceStrategy` / `PolicyConfidenceStrategy`, `LifecycleStrategy` / `DefaultLifecycleStrategy`.

> The kernel API is public but **provisional until v1.0**.

## CLI

```bash
typedmem profiles                                            # list built-in domain profiles
typedmem --profile research_paper add "..." --document-id paper.pdf
typedmem --profile engineering_design list --type decision
typedmem search "blood pressure" --type evidence
typedmem evolve --evolver contradictions
typedmem evolve --evolver goals --apply --threshold 0.9      # dry-run by default
typedmem history MEMORY_ID                                   # per-memory event timeline
typedmem timeline --subject storage_backend --source evolver # filter the event log
typedmem changed-since 1h                                    # canonical change feed (also: 5m, 2h, 1d, 1w, or ISO 8601)
typedmem workspaces
```

CLI writes (`add` / `delete`) are tagged `source="user"` in the event log, so `typedmem timeline --source user` shows exactly what a human did at the terminal vs. what an agent or evolver did.

Default store: `~/.typedmem/memories.db` (override with `--store path.db` or `--store path.jsonl`).

## Status & roadmap

Latest: **v0.6.0** — typed memory timeline (this release): every change emits a `MemoryEvent`; `store.history()` / `timeline()` / `changed_since()` give you the canonical change feed.

Prior: **v0.5.0** — `AgentMemory` four-verb contract (`remember` / `recall` / `reflect` / `forget`); **v0.4.x** — profiles, workspaces, evolvers, conflict-resolution audit trail.

Under consideration for **v0.7+**, only if real usage demands it:

- `VersionPolicy` as a separate per-type axis (deferred from v0.6 — overlapped messily with `ConflictPolicy`)
- Sync / replication engine on top of `changed_since()`
- Hybrid BM25 + semantic retrieval
- Sentence-transformer embedder

What TypedMemory **doesn't** do and doesn't plan to:

- ship document chunkers / loaders — define the `ingest()` seam, bring your own (`unstructured`, `langchain`, plain regex)
- ship its own vector DB — the abstraction is ready for one, but brute-force cosine wins under ~50k memories
- pull network dependencies into the default install — every provider is an opt-in extra

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome. Please run `pytest` and the demos in `examples/` before opening a PR; CI runs them on Python 3.10/3.11/3.12.

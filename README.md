# TypedMemory

**Typed, policy-aware, evolving memory layer for AI agents.**

[![CI](https://github.com/canis-minor/typedmem/actions/workflows/ci.yml/badge.svg)](https://github.com/canis-minor/typedmem/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/typedmem.svg)](https://pypi.org/project/typedmem/)
[![Python](https://img.shields.io/pypi/pyversions/typedmem.svg)](https://pypi.org/project/typedmem/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

📦 [PyPI](https://pypi.org/project/typedmem/) · 📚 [Docs](https://canis-minor.github.io/typedmem/) · 🏷️ [Releases](https://github.com/canis-minor/typedmem/releases) · 📝 [Changelog](CHANGELOG.md)

TypedMemory is the layer that sits between data and reasoning. Every memory has a **type** (claim, decision, observation, …), a **confidence**, a **structured source**, a **lifecycle policy**, and a **workspace** — not just a string in a vector database. Memories know how to update themselves on conflict, how to decay, and how to be summarized.

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

**Zero runtime dependencies.** Stdlib only. LLM clients, YAML profile loading, and sentence-transformer-style retrieval are optional extras.

## Why this exists

Most "AI memory" libraries are wrappers around a vector database. That's fine for "remember what the user said," but it falls apart the moment you want an agent to:

- track **who said what, in which document, at which span** (provenance)
- handle **the same fact from three sources** without storing it three times (reinforcement)
- recognize that **a new decision supersedes the old one** without losing the audit trail
- **summarize stale events** without throwing away the originals
- **isolate** legal memory from medical memory on the same machine
- **flag contradictions** instead of silently overwriting them

TypedMemory handles these as first-class concepts, not bolt-ons.

## Install

```bash
pip install typedmem
```

Optional extras:

```bash
pip install 'typedmem[anthropic]'    # AnthropicClient
pip install 'typedmem[openai]'       # OpenAIClient
pip install 'typedmem[yaml]'         # DomainProfile.from_yaml()
pip install 'typedmem[all]'
```

Python 3.10+.

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
| `SQLiteMemoryStore` | SQLite file | Indexed on `(workspace, type, subject)`; persists embeddings; auto-migrates v0.2 → v0.4 schemas |

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

Every action emits an `EvolutionRecord` (`evolver`, `action`, `input_ids`, `output_ids`, `reason`, `timestamp`) and gets appended to each affected memory's `metadata["evolution_history"]`. No black-box mutations.

## CLI

```bash
typedmem profiles                                            # list built-in domain profiles
typedmem --profile research_paper add "..." --document-id paper.pdf
typedmem --profile engineering_design list --type decision
typedmem search "blood pressure" --type evidence
typedmem evolve --evolver contradictions
typedmem evolve --evolver goals --apply --threshold 0.9      # dry-run by default
typedmem history MEMORY_ID                                   # audit trail for one memory
typedmem workspaces
```

Default store: `~/.typedmem/memories.db` (override with `--store path.db` or `--store path.jsonl`).

## Status & roadmap

v0.4 is the first public release.

- **v0.5** sentence-transformer embedder, profile composition (`extends`), destructive compaction (`MemoryStore.compact_summaries()`)
- **v0.6** hybrid BM25+semantic retrieval, query DSL, observability hooks

What TypedMemory **doesn't** do and doesn't plan to:

- ship document chunkers / loaders — define the `ingest()` seam, bring your own (`unstructured`, `langchain`, plain regex)
- ship its own vector DB — the abstraction is ready for one, but brute-force cosine wins under ~50k memories
- pull network dependencies into the default install — every provider is an opt-in extra

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome. Please run `pytest` and the demos in `examples/` before opening a PR; CI runs them on Python 3.10/3.11/3.12.

# Changelog

All notable changes to TypedMemory.

## [0.4.0] — 2026-05-15

First public release. The library now extracts, stores, retrieves, and **evolves** structured memory for AI agents — a complete pipeline behind one zero-dependency install.

### v0.4c — Memory Evolution
- New `Evolver` protocol, symmetric to `Extractor` but reading existing memories.
- `EvolutionRecord` / `EvolutionResult` provide a per-action audit trail.
- `ContradictionSurfacer` — pure-read graph walk over `metadata["conflicts_with"]`.
- `PreferenceDriftDetector` — uses `metadata["replace_log"]` (auto-written on every REPLACE) to flag unstable preferences.
- `GoalResolver` — semantic match between active goals and evidence; strict-by-default threshold (0.85); `dry_run` previews; one-level `revert`.
- `SummaryEvolver` — **non-destructive**: clusters stale memories by `(workspace, type, subject)`, asks an LLM for one short summary, creates a new memory linked via `metadata["summarizes"]`. Originals never modified or deleted.
- Every mutating action writes an `EvolutionRecord` into the affected memory's `metadata["evolution_history"]` (capped at 50 entries).
- Store helpers: `MemoryStore.contradictions()`, `drift_flags()`, `evolution_history(id)`.
- CLI: `typed-memory evolve --evolver {contradictions,drift,goals} [--apply]`; `typed-memory history MEMORY_ID`.

### v0.4b — Domain Profiles
- `TypeSpec` + `DomainProfile` make the type system pluggable.
- Seven built-in profiles: `core`, `personal`, `child_development`, `research_paper`, `engineering_design`, `legal`, `medical_literature`.
- Profiles can opt into shared `core` types (fact/note/goal/task/event) via `include_core_types=True` or `DomainProfile.with_core(...)`.
- `LLMExtractor(profile=...)` validates extracted memories against the profile's declared types and `required_fields`.
- `MemoryStore.for_profile(profile, ...)` enforces strict write-time validation.
- `Memory.type` is now a string; `MemoryType` enum stays importable as a back-compat alias.
- `PolicyEngine` rekeyed to strings; `from_profile()` classmethod.
- Profile loaders: `from_json()` (stdlib), `from_yaml()` (optional `[yaml]` extra).
- CLI: `--profile NAME`, `--profile-file PATH`, `typed-memory profiles` subcommand.

### v0.4a — Foundation
- Structured `Source` provenance (`document_id`, `chunk_id`, `span`, `retrieved_at`, `authority`); `Source.key()` for REINFORCE dedup.
- `workspace` namespace on every `Memory`; queries default to `default_workspace`; `MemoryStore.workspaces()`.
- Six-way `ConflictPolicy`: `REPLACE` / `KEEP_BOTH` / `SUPERSEDE` / `REINFORCE` / `FLAG` / `IGNORE`.
- `PolicyEngine.resolve()` returns a `ConflictAction`; weaker incoming downgrades REPLACE to IGNORE.
- `MemoryStore._apply_conflict` dispatches all six policies.
- SQLite migration runner (no JSON1 dependency); legacy `source: str` lifted into structured `sources: list[Source]`.
- CLI: `--workspace`, `workspaces` subcommand, `--document-id` / `--uri` / `--authority` on `add`.

### v0.3 — LLM Extraction Layer
- `LLMClient` protocol; `FakeClient` for offline tests; `OpenAIClient` (extra `[openai]`); `AnthropicClient` (extra `[anthropic]`).
- `LLMExtractor` with `ExtractionResult` debug shape (`raw_response`, `parsed_json`, `validation_errors`, `accepted_memories`).
- Tolerant JSON parsing: strips code fences, recovers arrays from prose-wrapped output.
- Built-in prompt templates: `general`, `child_development`.

### v0.2 — Durable + Searchable Memory
- `JSONLMemoryStore` (append-only with last-write-wins, `compact()`).
- `SQLiteMemoryStore` (indexed, persists embeddings).
- `EmbeddingProvider` protocol; `HashingEmbeddingProvider` default (zero-dep).
- `Retriever.relevant()` blends semantic + recency + decayed confidence.
- CLI: `add`, `search`, `list`, `delete`, `compact`.

### v0.1 — Foundation
- `Memory` dataclass + `MemoryType` enum.
- Five-type `PolicyEngine` with half-life decay.
- `RuleBasedExtractor`.
- `InMemoryStore`.
- Child-development tracking demo.

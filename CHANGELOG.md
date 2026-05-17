# Changelog

All notable changes to TypedMemory.

## [0.5.0] — 2026-05-16

Positioning shift: **long-term memory + reflection layer for AI agents.** Same primitives underneath, but now there's a clean four-verb front door for agent frameworks to plug into, and the README leads with what the library *does for an agent* rather than how it's structured underneath.

### Added
- **`AgentMemory` class** — the four-verb contract over the whole pipeline:
  - `remember(text, *, subject=None, source=None)` — extracts + stores; returns the memories added.
  - `recall(query, *, limit=10, types=None, tags=None, since=None)` — semantic + recency + confidence blend, scoped to this agent's workspace.
  - `reflect(*, dry_run=False, include_summary=False)` — runs the evolver pipeline (contradictions / drift / goals / optional LLM summarization) and returns an `AgentMemoryReflection`.
  - `forget(memory_id)` — explicit deletion for privacy / cleanup.
- **`AgentMemoryReflection` dataclass** — aggregated reflection result with a one-line `.summary()` for logging.
- **`typedmem contradictions` CLI verb** — first-class subcommand for the killer feature. Same logic as `evolve --evolver contradictions` but shorter to type and recommend.
- **`examples/agent_loop_demo.py`** — before-vs-after demo: five user utterances, run twice, only the second run can answer "what does the user prefer right now?" or "are they flipping a lot?".
- **README rewrite** — leads with the four-verb agent API; sharpened opening hook ("AI agents start believing their own hallucinations").

### Notes
- `AgentMemory` is purely a wrapper around existing primitives — no new logic, no behavior change. v0.4.x code using `MemoryStore` / `Retriever` / Evolvers directly continues to work unchanged.
- The agent-loop demo intentionally uses only the default `personal` profile and the rule-based extractor; no LLM key required.

## [0.4.2] — 2026-05-16

Conflict resolutions now leave an audit trail — the same surface Evolvers populate. The "debug hallucinating agents" story is finally backed by data you can actually inspect.

### Added
- `_apply_conflict` writes an `EvolutionRecord`-shaped entry to `metadata["evolution_history"]` for every state change:
  - **SUPERSEDE** — `superseded` on the old memory + `supersedes` on the new
  - **REPLACE** — `replaced` with a snippet of the prior content
  - **REINFORCE** — `reinforced` with the new source ids merged in (only when there are new unique sources)
  - **FLAG** — `flagged` on both memories, cross-referencing
- `typedmem history MEMORY_ID` now returns a meaningful lifecycle for memories that were superseded, replaced, reinforced, or flagged. Previously it returned "(no evolution history)" because only Evolver actions wrote to it.
- README **Use cases** section — debugging hallucinating agents, multi-doc RAG with provenance, long-running personal assistants, design-doc agents, multi-tenant agents.

### Notes
- KEEP_BOTH intentionally writes nothing — it's not a state change worth logging.
- `evolver: "store"` distinguishes conflict-resolution entries from Evolver-produced ones in the same history list.

## [0.4.1] — 2026-05-16

Quality-of-life patch addressing first-paste UX feedback after the v0.4.0 launch.

### Added
- `RuleBasedExtractor` now recognizes residence and affiliation patterns: `lives in / lives at / based in / works at / works for / studies at / is from / am from`. These land as `fact` memories so casual biographical statements no longer return "no memories extracted".
- Goal patterns now match third-person (`user wants to`, `she plans to`, `he is going to`) in addition to first-person. Previously only `i want to` / `we want to` matched.

### Fixed
- The CLI's `evolve --evolver contradictions` now prints the **contents** of each clustered memory instead of just their UUIDs — readable enough to paste into a README or demo recording.

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
- CLI: `typedmem evolve --evolver {contradictions,drift,goals} [--apply]`; `typedmem history MEMORY_ID`.

### v0.4b — Domain Profiles
- `TypeSpec` + `DomainProfile` make the type system pluggable.
- Seven built-in profiles: `core`, `personal`, `child_development`, `research_paper`, `engineering_design`, `legal`, `medical_literature`.
- Profiles can opt into shared `core` types (fact/note/goal/task/event) via `include_core_types=True` or `DomainProfile.with_core(...)`.
- `LLMExtractor(profile=...)` validates extracted memories against the profile's declared types and `required_fields`.
- `MemoryStore.for_profile(profile, ...)` enforces strict write-time validation.
- `Memory.type` is now a string; `MemoryType` enum stays importable as a back-compat alias.
- `PolicyEngine` rekeyed to strings; `from_profile()` classmethod.
- Profile loaders: `from_json()` (stdlib), `from_yaml()` (optional `[yaml]` extra).
- CLI: `--profile NAME`, `--profile-file PATH`, `typedmem profiles` subcommand.

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

# Changelog

All notable changes to TypedMemory.

## [0.6.2] — 2026-05-18

The v0.6 event log gets a CLI surface, and the CLI stops lying about who wrote what.

### Added
- **`typedmem timeline`** — filter the event log by `--subject` / `--type` / `--source` / `--all-workspaces`. AND-combined; omit a filter to match anything. `--json` for piping.
- **`typedmem changed-since <spec>`** — canonical change feed since a point in time. Accepts ISO 8601 (`2026-05-17T12:00:00`) or a relative spec (`5m`, `2h`, `1d`, `1w`, `30s`). Same `--json` flag.
- **`typedmem history --json`** — emit raw `MemoryEvent` dicts for scripting.

### Changed
- **`typedmem add` and `typedmem delete` now tag events as `source="user"`** (with `source_name="cli:add"` / `"cli:delete"`). Previously every CLI write looked indistinguishable from a programmatic `store.add()` — `source="store"`. Now `timeline --source user` shows exactly what a human did through the CLI.
- **`typedmem history` output** gains a source column: `[user/cli:add]`, `[evolver/preference_drift_detector]`, etc. The pre-v0.6.2 format had only `[evolver_name]` which silently labeled `store`-emitted lifecycle events as `[store]`.

### Notes
- No Python API changes from 0.6.1; this release is CLI surface only.

## [0.6.1] — 2026-05-18

### Added
- **`examples/belief_refinement_demo.py`** — the canonical v0.6 use case in 60 lines. Simulates four conversations refining the agent's model of a user's testing preferences and walks through `store.history()`, `store.changed_since()`, and the backwards-compatible `store.evolution_history()`. Belief *refinement* over time, not contrived flip-flop reversals.

### Notes
- No API or behavior changes from 0.6.0; this is a docs-and-demo patch.

## [0.6.0] — 2026-05-17

**Typed memory timeline.** Agents remember not only what they know, but how their beliefs changed over time. The pre-v0.6 `metadata["evolution_history"]` audit list is promoted into a first-class, indexed event log — every `add` / `update` / `delete` emits a typed `MemoryEvent`, not just contested writes. The event stream is the canonical memory change feed.

### Added
- **`MemoryEvent` dataclass** (`typedmem.events`) — typed, round-trippable, with fields `memory_id`, `workspace`, `type`, `subject`, `action`, `source`, `source_name`, `reason`, `input_ids`, `output_ids`, `payload`, `timestamp`, `id`.
- **`EventSource` literal type** — `"store" | "evolver" | "agent" | "user" | "system"`:
  - `store` — automatic lifecycle from `MemoryStore.add/update/delete`
  - `evolver` — `ContradictionSurfacer` / `GoalResolver` / `SummaryEvolver` / `PreferenceDriftDetector`
  - `agent` — caller explicitly tags an agent write (e.g. `AgentMemory.remember`)
  - `user` — caller explicitly tags a human action
  - `system` — migration, import, maintenance (e.g. lazy `evolution_history` migration)
- **Timeline query APIs** on every store:
  - `store.history(memory_id)` — every event for one memory, oldest first; includes the `deleted` event even after the memory row is gone.
  - `store.timeline(subject=..., type=..., workspace=..., source=...)` — filtered event stream.
  - `store.changed_since(timestamp)` — canonical change feed for consumers staying in sync; includes adds, updates, deletes, and evolver-driven transforms.
- **Event-source kwargs on the public API**: `store.add(memory, event_source="agent", event_source_name="agent_loop")` and `store.delete(memory_id, event_source=..., event_source_name=...)`. Defaults are `"store"` / `None`, preserving all v0.5 call sites.
- **`AgentMemory.remember()`** passes `event_source="agent"`, `event_source_name="AgentMemory.remember"`; `AgentMemory.forget()` passes `event_source="agent"`, `event_source_name="AgentMemory.forget"`.
- **SQLite `memory_events` table** with indexes on `memory_id`, `workspace`, `(workspace, type)`, `(workspace, type, subject)`, `timestamp`. Schema upgrades automatically on first open of an existing v0.5 database.
- **JSONLMemoryStore sidecar `.events.jsonl`** file. Memory file `compact()` does NOT compact events — the timeline is the historical record.

### Changed
- **`_record_lifecycle_event`** and **`annotate_history`** now write to the event log instead of `metadata["evolution_history"]`. The 50-entry-per-memory cap is gone.
- **`annotate_history(memory, record)` → `annotate_history(store, memory, record)`** — signature changed; callers in `drift.py`, `goals.py`, `summary.py` updated. External callers using the pre-v0.6 signature will see `TypeError` — update to the new signature.
- **`store.evolution_history(memory_id)`** still returns `list[dict]` in the pre-v0.6 shape, but is now backed by the event log. Entries that lived in `metadata["evolution_history"]` migrate lazily on first access with `source="system"`, `source_name="migrate_evolution_history"`.

### Not in 0.6
- `VersionPolicy` as a separate axis (`HISTORY` / `IMMUTABLE` etc.) — deferred to 0.7. Overlapped with `ConflictPolicy` in confusing ways (`HISTORY` + `REPLACE` is a contradiction; `IMMUTABLE` mostly duplicates `IGNORE`/`FLAG`). Will revisit only if real usage shows per-type timeline behavior needs to differ.
- Sync engine, replication, event replay — `changed_since()` is the quiet side door, but not yet a full mechanism.

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

# CLI

After installing TypedMemory, the `typed-memory` shell command is on your PATH.

```bash
typed-memory --help
```

## Global options

| Flag | Default | Notes |
|---|---|---|
| `--store PATH` | `~/.typed_memory/memories.db` | `.db` → SQLite, `.jsonl` → JSONL. Override via `$TYPED_MEMORY_DB` |
| `--workspace NAME` | `default` | Memory namespace; isolates one agent/domain from another |
| `--profile NAME` | _(none)_ | Built-in domain profile to bind: validates types and required fields, applies per-type policies |
| `--profile-file PATH` | _(none)_ | Path to a custom profile in `.json` or `.yaml` |

## Subcommands

### `add`

Add a memory (or extract from text via `RuleBasedExtractor` if no `--type`).

```bash
typed-memory add "I prefer concise answers"
typed-memory --profile engineering_design add "Use SQLite for storage" \
  --type decision --subject storage_backend \
  --document-id design_v1.md --authority 0.95
```

Options: `--type`, `--subject`, `--tags`, `--confidence`, `--document-id`, `--uri`, `--authority`.

### `search`

Semantic search across stored memories. Uses `HashingEmbeddingProvider` by default; `--no-embed` falls back to token overlap.

```bash
typed-memory search "blood pressure reduction" --type evidence --limit 5
typed-memory search "ship" --include-superseded
```

Options: `--limit`, `--type` (repeatable), `--tag` (repeatable), `--include-superseded`, `--no-embed`, `--dim`.

### `list`

List stored memories, newest first.

```bash
typed-memory list --type observation
typed-memory --workspace medical list --json
```

### `delete`

Delete by id.

```bash
typed-memory delete MEMORY_ID
```

### `compact`

Compact a JSONL store (rewrite as one record per live memory).

```bash
typed-memory --store memories.jsonl compact
```

### `workspaces`

List workspaces present in the store.

```bash
typed-memory workspaces
```

### `profiles`

List built-in domain profiles and their types.

```bash
typed-memory profiles
```

### `evolve`

Run an Evolver over the store.

```bash
typed-memory evolve --evolver contradictions
typed-memory evolve --evolver drift --apply
typed-memory evolve --evolver goals --threshold 0.9            # dry-run
typed-memory evolve --evolver goals --threshold 0.9 --apply    # commit
```

| Flag | Notes |
|---|---|
| `--evolver` | One of `contradictions`, `drift`, `goals` |
| `--apply` | Required to mutate. `drift` and `goals` default to dry-run for safety |
| `--threshold` | `goals` only — minimum cosine similarity to resolve (default `0.85`) |
| `--min-replaces` | `drift` only — REPLACE count threshold (default `3`) |
| `--window-days` | `drift` only — trailing window for replace counting (default `30`) |
| `--dim` | Hashing embedder dimension (`goals` only) |

`SummaryEvolver` is intentionally not exposed via CLI — it needs an LLM client; use the Python API.

### `history`

Show the `metadata["evolution_history"]` audit trail for a memory.

```bash
typed-memory history MEMORY_ID
```

## Conventions

- Read-only commands never need `--apply`.
- Evolver mutations always require explicit opt-in.
- Output is plain text by default; `list --json` emits structured JSON.

## Example: a typical agent session

```bash
# Capture the design discussion
typed-memory --profile engineering_design --workspace project_x add \
  "Use SQLite for storage" --type decision --subject storage_backend \
  --document-id design_v1.md

typed-memory --profile engineering_design --workspace project_x add \
  "Switch to PostgreSQL" --type decision --subject storage_backend \
  --document-id design_v2.md

# Look at the active decision and the audit trail
typed-memory --workspace project_x list --type decision
typed-memory --workspace project_x list --type decision --include-superseded

# Surface any flagged risks
typed-memory --workspace project_x evolve --evolver contradictions
```

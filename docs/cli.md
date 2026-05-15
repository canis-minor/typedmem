# CLI

After installing TypedMemory, the `typedmem` shell command is on your PATH.

```bash
typedmem --help
```

## Global options

| Flag | Default | Notes |
|---|---|---|
| `--store PATH` | `~/.typedmem/memories.db` | `.db` → SQLite, `.jsonl` → JSONL. Override via `$TYPEDMEM_DB` |
| `--workspace NAME` | `default` | Memory namespace; isolates one agent/domain from another |
| `--profile NAME` | _(none)_ | Built-in domain profile to bind: validates types and required fields, applies per-type policies |
| `--profile-file PATH` | _(none)_ | Path to a custom profile in `.json` or `.yaml` |

## Subcommands

### `add`

Add a memory (or extract from text via `RuleBasedExtractor` if no `--type`).

```bash
typedmem add "I prefer concise answers"
typedmem --profile engineering_design add "Use SQLite for storage" \
  --type decision --subject storage_backend \
  --document-id design_v1.md --authority 0.95
```

Options: `--type`, `--subject`, `--tags`, `--confidence`, `--document-id`, `--uri`, `--authority`.

### `search`

Semantic search across stored memories. Uses `HashingEmbeddingProvider` by default; `--no-embed` falls back to token overlap.

```bash
typedmem search "blood pressure reduction" --type evidence --limit 5
typedmem search "ship" --include-superseded
```

Options: `--limit`, `--type` (repeatable), `--tag` (repeatable), `--include-superseded`, `--no-embed`, `--dim`.

### `list`

List stored memories, newest first.

```bash
typedmem list --type observation
typedmem --workspace medical list --json
```

### `delete`

Delete by id.

```bash
typedmem delete MEMORY_ID
```

### `compact`

Compact a JSONL store (rewrite as one record per live memory).

```bash
typedmem --store memories.jsonl compact
```

### `workspaces`

List workspaces present in the store.

```bash
typedmem workspaces
```

### `profiles`

List built-in domain profiles and their types.

```bash
typedmem profiles
```

### `evolve`

Run an Evolver over the store.

```bash
typedmem evolve --evolver contradictions
typedmem evolve --evolver drift --apply
typedmem evolve --evolver goals --threshold 0.9            # dry-run
typedmem evolve --evolver goals --threshold 0.9 --apply    # commit
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
typedmem history MEMORY_ID
```

## Conventions

- Read-only commands never need `--apply`.
- Evolver mutations always require explicit opt-in.
- Output is plain text by default; `list --json` emits structured JSON.

## Example: a typical agent session

```bash
# Capture the design discussion
typedmem --profile engineering_design --workspace project_x add \
  "Use SQLite for storage" --type decision --subject storage_backend \
  --document-id design_v1.md

typedmem --profile engineering_design --workspace project_x add \
  "Switch to PostgreSQL" --type decision --subject storage_backend \
  --document-id design_v2.md

# Look at the active decision and the audit trail
typedmem --workspace project_x list --type decision
typedmem --workspace project_x list --type decision --include-superseded

# Surface any flagged risks
typedmem --workspace project_x evolve --evolver contradictions
```

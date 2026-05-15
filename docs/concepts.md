# Concepts

Four primitives carry the design.

## Memory

A typed dataclass — not just text in a bag.

```python
from typed_memory import Memory, Source

m = Memory(
    type="claim",
    content="Drug X reduces blood pressure",
    confidence=0.85,
    subject="drug_x",
    workspace="medical",
    sources=[Source(document_id="paper_a.pdf", chunk_id="results", span=(120, 240))],
    tags=["cardiology"],
)
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `type` | `str` | Built-in (`fact`/`preference`/…) or profile-defined (`claim`/`decision`/…) |
| `content` | `str` | The actual memory text |
| `confidence` | `float` | `[0, 1]`; decays per type's `half_life_days` |
| `subject` | `str \| None` | Who/what — part of the conflict slot key |
| `tags` | `list[str]` | Free-form (or constrained by `TypeSpec.allowed_tags`) |
| `workspace` | `str` | Namespace; defaults to `"default"` |
| `sources` | `list[Source]` | Provenance — see below |
| `status` | `str \| None` | E.g. `"active"`/`"resolved"` for goals |
| `superseded_by` | `str \| None` | Set by `SUPERSEDE` policy or evolvers |
| `metadata` | `dict[str, Any]` | Library-managed fields (`replace_log`, `conflicts_with`, `evolution_history`, …) plus user-defined keys |

`Memory.type` is plain `str` so profiles can register custom types. The `MemoryType` enum (`MemoryType.FACT == "fact"`, etc.) is kept as a back-compat alias.

## Source — structured provenance

Without provenance, a `claim` is just a sentence. With it, you can cite, deduplicate, and trust-weight.

```python
from typed_memory import Source

Source(
    document_id="paper_a.pdf",     # opaque, caller-chosen
    chunk_id="results",            # optional: which section/chunk
    span=(120, 240),               # optional: char offsets
    retrieved_at=...,              # defaults to now (UTC)
    authority=0.95,                # used as weight in REINFORCE
    uri="https://arxiv.org/abs/..." # optional
)
```

`Source.key()` returns `(document_id, chunk_id, span)` — the dedup identity for `REINFORCE`. Two chunks from the same document independently corroborating a memory are kept as distinct evidence.

`Source.from_any(value)` lifts strings into Sources for v0.3 backward compat.

## Workspace — namespace isolation

Every `Memory` has a `workspace: str` (default `"default"`). Conflict resolution is workspace-scoped: a `preference` with subject `"user"` in workspace `"legal"` never collides with the same in workspace `"medical"`.

```python
store = SQLiteMemoryStore("memories.db", default_workspace="legal")
# … all queries default to 'legal'; override per-call with workspace=...
```

CLI:

```bash
typed-memory --workspace legal add "..." --type obligation
typed-memory workspaces
```

## ConflictPolicy — the intelligence layer

When you `store.add(memory)` and a memory with the same `(workspace, type, subject)` slot already exists, the type's `ConflictPolicy` decides what happens:

| Policy | What it does |
|---|---|
| `REPLACE` | Existing record updated in place (same id). Newer-and-stronger wins; weaker incoming downgrades to `IGNORE` |
| `KEEP_BOTH` | Both stored independently; no link |
| `SUPERSEDE` | Old gets `superseded_by = new.id` and stays in store; new is the active record |
| `REINFORCE` | Single record; sources unioned by `(document_id, chunk_id, span)`; confidence boosted by authority-weighted blend |
| `FLAG` | Both stored; each gets `metadata["conflicts_with"]` pointing at the other |
| `IGNORE` | Incoming discarded; existing untouched. Also auto-applied when REPLACE-target incoming is strictly weaker |

The right policy depends on what the type *means*:

- A user's **preference** changes → `REPLACE`
- A scientific **claim** can have multiple competing answers → `KEEP_BOTH`
- An engineering **decision** evolves but the audit trail matters → `SUPERSEDE`
- **Evidence** for the same outcome from two papers → `REINFORCE`
- A safety **risk** with two contradictory readings → `FLAG`

These defaults live in `DomainProfile.builtin(...)` — see [Profiles](profiles.md).

## How they compose

```
   Memory.add()
      │
      ▼
   (workspace, type, subject) slot lookup
      │
      ├── empty   → store directly
      │
      └── occupied → PolicyEngine.resolve(existing, incoming)
                     │
                     ▼
                  ConflictAction { REPLACE | KEEP_BOTH | SUPERSEDE | REINFORCE | FLAG | IGNORE }
                     │
                     ▼
                  store mutation + metadata updates
```

Same flow whether the memory came from `RuleBasedExtractor`, `LLMExtractor`, or your own code. Same flow whether the backend is `InMemoryStore`, `JSONLMemoryStore`, or `SQLiteMemoryStore`.

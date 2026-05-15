# Profiles

A `DomainProfile` is the schema layer: which memory types exist for a domain, what conflict policy each obeys, what fields are required, what tags are allowed, and what prompt template the LLM should use.

## Built-in profiles

| Profile | Domain types | Notable policies |
|---|---|---|
| `core` | fact, note, goal, task, event | The shared knowledge primitives. Other profiles can opt into this set. |
| `personal` | + preference, observation | `preference → REPLACE (60d decay)` |
| `child_development` | + observation (tagged), milestone, concern | observation tags limited to language/motor/emotional/cognitive/social |
| `research_paper` | + claim, method, evidence, limitation, open_question | **evidence → REINFORCE** (multiple papers corroborate) |
| `engineering_design` | + decision, constraint, risk, assumption, todo | **decision → SUPERSEDE**, **risk → FLAG** |
| `legal` | + obligation, exception, deadline, definition, citation | **definition → SUPERSEDE**; obligation requires source + subject |
| `medical_literature` | + finding, population, intervention, outcome, limitation | **outcome → REINFORCE** across studies |

```python
from typedmem import DomainProfile

profile = DomainProfile.builtin("research_paper")
profile.all_types()       # dict[str, TypeSpec]   — core + domain types merged
profile.policies()        # dict[str, TypePolicy] — keyed by type name
```

## TypeSpec

```python
from typedmem import TypeSpec, ConflictPolicy

TypeSpec(
    name="evidence",
    description="A result/figure that supports a claim",
    conflict_policy=ConflictPolicy.REINFORCE,
    half_life_days=None,
    summarizable=False,
    required_fields=("source",),       # "source" → sources list must be non-empty
    allowed_tags=None,                  # None = open vocabulary; tuple = strict
)
```

Required-fields shorthand:

- `"source"` — at least one entry in `memory.sources`
- `"subject"` — non-empty `memory.subject`
- `"tags"` — non-empty `memory.tags`
- any other dataclass field name on `Memory` — must be non-empty

## Custom profiles

### From Python

```python
from typedmem import DomainProfile, TypeSpec, ConflictPolicy

contracts = DomainProfile(
    name="contracts",
    description="Capture obligations from legal contracts.",
    include_core_types=True,   # opt into fact/note/goal/task/event from core
    types={
        "obligation": TypeSpec(
            name="obligation",
            conflict_policy=ConflictPolicy.KEEP_BOTH,
            required_fields=("source", "subject"),
        ),
        "deadline": TypeSpec(
            name="deadline",
            conflict_policy=ConflictPolicy.REPLACE,
            required_fields=("subject",),
        ),
    },
    prompt_template="""\
You are a contract memory extractor.

Available types:
  obligation   (requires source + subject)
  deadline     (requires subject)
  fact, note, goal, task, event   (core types)

Return ONLY a JSON array. No prose, no code fences.

Subject context (may be empty): {subject}

Text:
\"\"\"
{text}
\"\"\"

JSON array:""",
)
```

### From JSON

```json
{
  "name": "contracts",
  "include_core_types": true,
  "types": {
    "obligation": {
      "name": "obligation",
      "conflict_policy": "keep_both",
      "required_fields": ["source", "subject"]
    },
    "deadline": {
      "name": "deadline",
      "conflict_policy": "replace",
      "required_fields": ["subject"]
    }
  },
  "prompt_template": "..."
}
```

```python
from typedmem.profiles import from_json
profile = from_json("contracts.json")
```

### From YAML

```yaml
name: contracts
include_core_types: true
types:
  obligation:
    name: obligation
    conflict_policy: keep_both
    required_fields: [source, subject]
  deadline:
    name: deadline
    conflict_policy: replace
    required_fields: [subject]
prompt_template: |
  ...
```

```python
from typedmem.profiles import from_yaml
profile = from_yaml("contracts.yaml")    # requires [yaml] extra
```

## Using profiles

### With LLMExtractor

```python
extractor = LLMExtractor(client=AnthropicClient(), profile=profile)
```

The extractor:

1. Uses `profile.prompt_template` (falls back to the generic template if `None`).
2. Validates each extracted record: type must be declared in the profile; `required_fields` must be present; `allowed_tags` must contain every emitted tag.
3. Drops invalid records and reports them in `ExtractionResult.validation_errors` — the rest of the batch is kept.

### With a store

```python
store = SQLiteMemoryStore.for_profile(profile, "memories.db")
```

A profile-bound store enforces validation at write time (raises `ValueError` on `add()` if the memory doesn't match the schema). Without a profile, stores are lenient — any type string is accepted.

## Composition

`include_core_types=True` merges the `core` profile's types under your domain types. Your declarations override on name collision (e.g. you can redeclare `event` with a different policy).

Full profile composition (`extends`) is planned for v0.5 — for now, copy what you need or load multiple profiles in your own code.

## Provisional defaults

The conflict policies on built-in profiles are tuned for plausibility, not derived from a benchmark. Treat them as a starting point — override per type by constructing your own `DomainProfile`.

# TypedMemory

**Typed, policy-aware, evolving memory layer for AI agents.**

TypedMemory is the layer that sits between data and reasoning. Every memory has a type, a confidence, a structured source, a lifecycle policy, and a workspace — not just a string in a vector database. Memories know how to update on conflict, how to decay, and how to be summarized.

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

**Zero runtime dependencies.** Stdlib only — LLM clients, YAML profile loading, and richer embedders are optional extras.

## Why this exists

Most "AI memory" libraries are wrappers around a vector database. That works for "remember what the user said," but it falls apart the moment you want an agent to:

- track **who said what, in which document, at which span**
- handle **the same fact from three sources** without storing it three times
- recognize that **a new decision supersedes the old one** without losing the audit trail
- **summarize stale events** without throwing away the originals
- **isolate** legal memory from medical memory on the same machine
- **flag contradictions** instead of silently overwriting them

TypedMemory treats these as first-class concepts.

## Start here

<div class="grid cards" markdown>

- :material-rocket-launch: **[Quickstart](quickstart.md)**

    Install, write your first memory, run the engineering-design demo.

- :material-lightbulb-outline: **[Concepts](concepts.md)**

    Source, workspace, ConflictPolicy, Memory — the four primitives.

- :material-file-tree: **[Profiles](profiles.md)**

    Schema for a domain: types, policies, prompt templates.

- :material-update: **[Evolvers](evolvers.md)**

    Contradiction surfacing, drift detection, goal resolution, summarization.

- :material-console-line: **[CLI](cli.md)**

    `typed-memory` shell tool — `add`, `search`, `evolve`, `history`, …

- :material-source-repository: **[Source on GitHub](https://github.com/ruxiz/typed-memory)**

    Code, tests, issues.

</div>

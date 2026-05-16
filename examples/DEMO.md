# TypedMemory — 30-second demo

Paste these commands into any terminal. Default install only, no flags beyond
`--subject user`.

```bash
pip install typedmem

typedmem add "User likes jazz"            --subject user
typedmem add "User lives in Tokyo"        --subject user
typedmem add "User wants to learn Rust"   --subject user

typedmem add "User likes hiphop now"      --subject user

typedmem list
```

Expected output:

```
added 1 memorie(s) from extractor
  2026-05-16 preference  [user] conf=0.85  User likes jazz

added 1 memorie(s) from extractor
  2026-05-16 fact        [user] conf=0.85  User lives in Tokyo

added 1 memorie(s) from extractor
  2026-05-16 goal        [user] conf=0.80  User wants to learn Rust

added 1 memorie(s) from extractor
  2026-05-16 preference  [user] conf=0.85  User likes hiphop now

2026-05-16 preference  [user] conf=0.85  User likes hiphop now
2026-05-16 goal        [user] conf=0.80  User wants to learn Rust
2026-05-16 fact        [user] conf=0.85  User lives in Tokyo
```

## What just happened

You typed **4 sentences**. The library kept **3 memories**.

- **Auto-typing**: each sentence was classified — `preference`, `fact`, `goal` —
  without you telling it the type.
- **Evolution**: the second `"User likes ..."` (hiphop) **replaced** the first
  (jazz) silently, because the `preference` type uses the REPLACE policy on a
  matching `(subject, type)` slot. Run `typedmem history <id>` on the
  preference and you'll see the audit entry:

  ```
  2026-05-16T07:30:00Z  [store] replaced: content updated (was: 'User likes jazz')
  ```

Both halves of the tagline land in one paste:

> structured knowledge — **and evolves it**.

---

## Recording it as an asciinema cast

For a shareable embed:

```bash
brew install asciinema          # macOS; on Linux: apt install asciinema
asciinema rec typedmem-demo.cast
# paste the commands above, then `exit`
asciinema upload typedmem-demo.cast
```

You'll get a `https://asciinema.org/a/<id>` URL you can drop into the README
between `<!-- demo -->` markers.

## Or just a screenshot

A clean terminal showing the final `typedmem list` output is enough — the type
column tells the story on its own. Crop to ~80 cols × 10 rows.

---

## Deeper demos in this folder

| File | Story |
|---|---|
| `engineering_design_demo.py` | Decisions get superseded; risks get flagged; full audit trail |
| `research_paper_demo.py` | Two papers' evidence REINFORCES into one memory with unioned sources |
| `evolution_demo.py` | All four Evolvers (contradictions, drift, goals, summarization) |
| `child_development_demo.py` | The original v0.1 use case |
| `llm_extraction_demo.py` | `LLMExtractor` via `FakeClient` (swap in Anthropic/OpenAI to go live) |

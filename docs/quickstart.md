# Quickstart

## Install

```bash
pip install typed-memory
```

For LLM extraction or richer file formats, add an extra:

```bash
pip install 'typed-memory[anthropic]'    # AnthropicClient
pip install 'typed-memory[openai]'       # OpenAIClient
pip install 'typed-memory[yaml]'         # DomainProfile.from_yaml()
pip install 'typed-memory[all]'
```

Requires Python 3.10+.

## Your first memory

```python
from typed_memory import InMemoryStore, Memory

store = InMemoryStore()
m = store.add(Memory(type="fact", content="The sky is blue"))
print(m.id, m.confidence, m.workspace)
```

## With a domain profile

A `DomainProfile` declares which types exist for a domain and how each behaves on conflict.

```python
from typed_memory import DomainProfile, SQLiteMemoryStore, Memory, Source

profile = DomainProfile.builtin("engineering_design")
store = SQLiteMemoryStore.for_profile(profile, "design.db")

store.add(Memory(
    type="decision",
    content="Use SQLite for storage",
    subject="storage_backend",
    sources=[Source(document_id="design_v1.md", chunk_id="sec-3")],
))
```

The `engineering_design` profile sets `decision → SUPERSEDE`: the next decision for the same subject will mark this one as superseded and become the active record.

## Extracting from text with an LLM

```python
from typed_memory import LLMExtractor, AnthropicClient, DomainProfile

extractor = LLMExtractor(
    client=AnthropicClient(),                           # needs [anthropic] extra
    profile=DomainProfile.builtin("research_paper"),
)

for m in extractor.extract(paper_text, default_source=Source(document_id="paper.pdf")):
    store.add(m)
```

For tests and offline development, use `FakeClient`:

```python
from typed_memory import FakeClient
extractor = LLMExtractor(
    client=FakeClient('[{"type": "claim", "content": "X improves Y", "confidence": 0.9}]'),
    profile=DomainProfile.builtin("research_paper"),
)
```

`ExtractionResult` carries full diagnostics (`raw_response`, `parsed_json`, `validation_errors`, `accepted_memories`) — pass `return_debug=True` to get it.

## Retrieval

```python
from typed_memory import Retriever, HashingEmbeddingProvider

r = Retriever(store, embedder=HashingEmbeddingProvider())
hits = r.relevant("blood pressure reduction", types=["evidence"], limit=5)
for hit in hits:
    print(hit.score, hit.memory.content)
```

Without an embedder, `relevant()` falls back to token-overlap matching.

## Evolution

The `Evolver` layer reads stored memories and produces auditable actions.

```python
from typed_memory import ContradictionSurfacer, GoalResolver, HashingEmbeddingProvider

# Pure read.
for cluster in store.contradictions():
    print(f"contradiction cluster of {len(cluster)} memories")

# Dry-run first.
plan = GoalResolver(HashingEmbeddingProvider(), threshold=0.85).evolve(store, dry_run=True)
print(plan.summary())
```

See **[Evolvers](evolvers.md)** for the full toolkit.

## Try the demos

After installing in editable mode (`pip install -e ".[test]"`), run:

```bash
python examples/engineering_design_demo.py
python examples/research_paper_demo.py
python examples/evolution_demo.py
python examples/child_development_demo.py
python examples/llm_extraction_demo.py
```

Each is self-contained and uses `FakeClient` so no API key is required.

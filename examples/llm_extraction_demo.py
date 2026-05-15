"""LLM extraction demo using FakeClient (no API key required).

Swap FakeClient for OpenAIClient or AnthropicClient to run against a real
provider — install with ``pip install 'typed-memory[openai]'`` or
``[anthropic]``.
"""

import json

from typed_memory import (
    FakeClient,
    HashingEmbeddingProvider,
    InMemoryStore,
    LLMExtractor,
    Retriever,
)


# Realistic Claude/GPT response for the child-development domain.
SCRIPTED_RESPONSE = json.dumps([
    {"type": "event", "content": "child said 'more milk' this morning",
     "confidence": 0.85, "subject": "child", "tags": ["morning"]},
    {"type": "observation", "content": "said 'more milk' clearly",
     "confidence": 0.9, "subject": "child", "tags": ["language"]},
    {"type": "observation", "content": "tried to put on her shoes",
     "confidence": 0.85, "subject": "child", "tags": ["motor"]},
    {"type": "preference", "content": "wants more milk",
     "confidence": 0.6, "subject": "child", "tags": ["food"]},
])


def main() -> None:
    client = FakeClient(SCRIPTED_RESPONSE)
    extractor = LLMExtractor(client, domain="child_development")
    store = InMemoryStore()

    text = "Today she said 'more milk' clearly and tried to put on her shoes."

    debug = extractor.extract(text, subject="child", return_debug=True)
    print(f"raw response ({len(debug.raw_response)} chars):\n{debug.raw_response[:160]}…\n")
    print(f"parsed: {len(debug.parsed_json or [])} records, "
          f"accepted: {len(debug.accepted_memories)}, "
          f"errors: {len(debug.validation_errors)}")
    if debug.validation_errors:
        for e in debug.validation_errors:
            print(f"  ! {e}")

    print("\n--- accepted memories ---")
    for m in debug.accepted_memories:
        store.add(m)
        tag_str = f" #{','.join(m.tags)}" if m.tags else ""
        print(f"  [{m.type}]{tag_str} ({m.confidence:.2f}) {m.content}")

    print("\n--- retrieval ---")
    retriever = Retriever(store, embedder=HashingEmbeddingProvider())
    for hit in retriever.relevant("toddler wanted milk"):
        print(f"  {hit.score:.2f}  [{hit.memory.type}] {hit.memory.content}")


if __name__ == "__main__":
    main()

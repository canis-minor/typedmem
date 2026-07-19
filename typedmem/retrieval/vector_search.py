"""Feature 3 — Vector candidate retrieval.

Vector search is used ONLY for candidate generation — it never decides final
correctness (that is the resolver + ranker's job). Reuses the existing
``EmbeddingProvider`` and ``cosine``; a memory's stored embedding
(``metadata["_embedding"]``) is reused when the embedder id matches.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..embeddings import EmbeddingProvider, cosine
from ..schema import Memory


class MemoryVectorizer:
    """Embeds ``Memory.content`` on demand with a per-instance cache. Prefers a
    persisted embedding when it was produced by the same embedder."""

    def __init__(self, embedder: EmbeddingProvider) -> None:
        self.embedder = embedder
        self._cache: dict[str, list[float]] = {}

    def vector(self, m: Memory) -> list[float]:
        cached = self._cache.get(m.id)
        if cached is not None:
            return cached
        stored = m.metadata.get("_embedding")
        if isinstance(stored, list) and m.metadata.get("_embedder_id") == self.embedder.id:
            self._cache[m.id] = stored
            return stored
        vec = self.embedder.embed([m.content])[0]
        self._cache[m.id] = vec
        return vec


@dataclass
class Candidate:
    memory: Memory
    similarity: float


def search_candidates(
    query: str,
    memories: list[Memory],
    *,
    embedder: EmbeddingProvider,
    vectorizer: MemoryVectorizer | None = None,
    top_k: int = 30,
) -> list[Candidate]:
    """Return the ``top_k`` memories by cosine similarity to ``query``. Similarity
    is clamped at 0 (negative cosine is treated as no signal)."""
    if not memories:
        return []
    vz = vectorizer or MemoryVectorizer(embedder)
    qvec = embedder.embed([query])[0]
    scored = [Candidate(m, max(0.0, cosine(qvec, vz.vector(m)))) for m in memories]
    scored.sort(key=lambda c: c.similarity, reverse=True)
    return scored[:top_k]

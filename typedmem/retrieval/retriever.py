"""Retrieval orchestrator — wires the v0 typed pipeline end to end.

    query
      ↓  typed routing        (router.route_query)
      ↓  typed filters        (filters.build_filters / apply_filters)
      ↓  vector candidates     (vector_search.search_candidates)
      ↓  temporal resolution   (resolver.resolve_temporal)
      ↓  reranking             (ranker.rerank)
      ↓  top-k

Each stage is a standalone function/dataclass in this package so it can be
benchmarked in isolation; this class just composes them.
"""

from __future__ import annotations

from datetime import datetime

from ..embeddings import EmbeddingProvider
from ..schema import Memory
from ..stores.base import MemoryStore
from .filters import apply_filters, build_filters
from .ranker import RankWeights, rerank
from .resolver import resolve_temporal
from .router import RetrievalIntent, route_query
from .vector_search import MemoryVectorizer, search_candidates


class TypedRetriever:
    """Minimal typed retrieval over a ``MemoryStore``.

    ``candidate_k`` bounds the vector-search pool handed to resolution/ranking;
    ``top_k`` (per call) is the final result size. Single-valued types (those
    whose conflict policy supersedes — ``TypePolicy.updatable``) are collapsed to
    their latest member during temporal resolution.
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        embedder: EmbeddingProvider,
        weights: RankWeights | None = None,
        recency_half_life_days: float = 30.0,
        candidate_k: int = 30,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.vectorizer = MemoryVectorizer(embedder)
        self.weights = weights or RankWeights()
        self.recency_half_life_days = recency_half_life_days
        self.candidate_k = candidate_k

    def _single_valued_types(self) -> set[str]:
        """Types whose conflict policy supersedes older values for the same slot,
        so temporal resolution should keep only the latest."""
        types: set[str] = set()
        for m in self.store:
            try:
                if self.store.policy.policy_for(m.type).updatable:
                    types.add(m.type)
            except KeyError:
                continue
        return types

    def retrieve(
        self,
        query: str,
        *,
        memory_types: list[str] | None = None,
        entity_ids: list[str] | None = None,
        status: str | None = None,
        as_of: datetime | None = None,
        top_k: int = 5,
        route: bool = True,
    ) -> list[Memory]:
        intent = route_query(query) if route else RetrievalIntent()
        filters = build_filters(
            intent,
            memory_types=memory_types,
            entity_ids=entity_ids,
            status=status,
            as_of=as_of,
            workspace=self.store.default_workspace,
        )
        pool = apply_filters(list(self.store), filters)
        candidates = search_candidates(
            query, pool, embedder=self.embedder,
            vectorizer=self.vectorizer, top_k=self.candidate_k,
        )
        resolved = resolve_temporal(
            [c.memory for c in candidates],
            as_of=as_of,
            collapse_types=self._single_valued_types(),
        )
        keep = {m.id for m in resolved}
        candidates = [c for c in candidates if c.memory.id in keep]
        ranked = rerank(
            candidates, intent=intent, weights=self.weights,
            recency_half_life_days=self.recency_half_life_days,
        )
        return [r.memory for r in ranked[:top_k]]

"""Query interface over a MemoryStore.

Blends three signals when an embedding provider is configured:
  semantic   — cosine similarity of query vs. memory embedding
  recency    — exponential boost with a configurable half-life (default 30d)
  confidence — policy-decayed confidence from PolicyEngine

Falls back to token-overlap relevance when no embedder is provided, so the
library still does something useful out of the box."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .embeddings import EmbeddingProvider, cosine
from .kernel import PolicyConfidenceStrategy
from .policy import PolicyEngine
from .schema import Memory, MemoryType
from .stores.base import MemoryStore
from .stores.sqlite import SQLiteMemoryStore


@dataclass
class ScoredMemory:
    memory: Memory
    score: float


@dataclass(frozen=True)
class RelevanceWeights:
    semantic: float = 0.6
    recency: float = 0.15
    confidence: float = 0.25


def _tokens(s: str) -> set[str]:
    raw = re.findall(r"[a-z0-9']+", s.lower())
    return {t.strip("'") for t in raw if t.strip("'")}


class Retriever:
    def __init__(
        self,
        store: MemoryStore,
        policy: PolicyEngine | None = None,
        embedder: EmbeddingProvider | None = None,
        recency_half_life_days: float = 30.0,
        weights: RelevanceWeights | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or store.policy
        # Confidence decay goes through a ConfidenceStrategy (RFC-0001). Default
        # to the store's strategy (honoring an injected one); with an explicit
        # policy override, build one from that policy so custom-policy decay is
        # preserved.
        self.confidence = store.confidence if policy is None else PolicyConfidenceStrategy(self.policy)
        self.embedder = embedder
        self.recency_half_life_days = recency_half_life_days
        self.weights = weights or RelevanceWeights()
        # In-process cache: memory id → vector. Persisted backends may already
        # carry a vector in metadata["_embedding"]; that takes precedence.
        self._cache: dict[str, list[float]] = {}

    # ---- Simple filters ------------------------------------------------------
    def by_type(self, t: MemoryType, *, workspace: str | None = None,
                include_superseded: bool = False) -> list[Memory]:
        return self.store.by_type(t, workspace=workspace, include_superseded=include_superseded)

    def by_tag(self, tag: str, *, workspace: str | None = None,
               include_superseded: bool = False) -> list[Memory]:
        ws = workspace if workspace is not None else self.store.default_workspace
        return [m for m in self.store
                if tag in m.tags and m.workspace == ws
                and (include_superseded or m.superseded_by is None)]

    def recent(self, limit: int = 10, *, workspace: str | None = None,
               include_superseded: bool = False) -> list[Memory]:
        items = self.store.all(workspace=workspace, include_superseded=include_superseded)
        return sorted(items, key=lambda m: m.timestamp, reverse=True)[:limit]

    def by_confidence(self, threshold: float = 0.7, *, apply_decay: bool = True,
                      workspace: str | None = None,
                      include_superseded: bool = False) -> list[Memory]:
        now = datetime.now(timezone.utc)
        scorer = (lambda m: self.confidence.decay(m, now)) if apply_decay else (lambda m: m.confidence)
        items = self.store.all(workspace=workspace, include_superseded=include_superseded)
        return sorted(
            (m for m in items if scorer(m) >= threshold),
            key=scorer, reverse=True,
        )

    # ---- Relevance -----------------------------------------------------------
    def relevant(
        self,
        query: str,
        *,
        limit: int = 10,
        types: list[MemoryType] | None = None,
        tags: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        workspace: str | None = None,
        include_superseded: bool = False,
    ) -> list[ScoredMemory]:
        candidates = self._filter(types, tags, since, until, workspace, include_superseded)
        if not candidates:
            return []
        if self.embedder is not None:
            scored = self._semantic_score(query, candidates)
        else:
            scored = self._token_score(query, candidates)
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:limit]

    def _filter(
        self,
        types: list[MemoryType] | None,
        tags: list[str] | None,
        since: datetime | None,
        until: datetime | None,
        workspace: str | None,
        include_superseded: bool,
    ) -> list[Memory]:
        out: list[Memory] = []
        tagset = set(tags) if tags else None
        ws = workspace if workspace is not None else self.store.default_workspace
        for m in self.store:
            if m.workspace != ws:
                continue
            if not include_superseded and m.superseded_by is not None:
                continue
            if types and m.type not in types:
                continue
            if tagset and not tagset.intersection(m.tags):
                continue
            if since and m.timestamp < since:
                continue
            if until and m.timestamp > until:
                continue
            out.append(m)
        return out

    def _vector_for(self, m: Memory) -> list[float]:
        cached = self._cache.get(m.id)
        if cached is not None:
            return cached
        stored = m.metadata.get("_embedding")
        if isinstance(stored, list) and m.metadata.get("_embedder_id") == self.embedder.id:  # type: ignore[union-attr]
            self._cache[m.id] = stored
            return stored
        vec = self.embedder.embed([m.content])[0]  # type: ignore[union-attr]
        self._cache[m.id] = vec
        # Persist for SQLite-backed stores so future processes skip the recompute.
        if isinstance(self.store, SQLiteMemoryStore):
            self.store.set_embedding(m.id, vec, self.embedder.id)  # type: ignore[union-attr]
        return vec

    def _semantic_score(self, query: str, candidates: list[Memory]) -> list[ScoredMemory]:
        qvec = self.embedder.embed([query])[0]  # type: ignore[union-attr]
        now = datetime.now(timezone.utc)
        w = self.weights
        results: list[ScoredMemory] = []
        for m in candidates:
            sem = max(0.0, cosine(qvec, self._vector_for(m)))
            rec = _recency_boost(m, now, self.recency_half_life_days)
            conf = self.confidence.decay(m, now)
            results.append(ScoredMemory(m, w.semantic * sem + w.recency * rec + w.confidence * conf))
        return results

    def _token_score(self, query: str, candidates: list[Memory]) -> list[ScoredMemory]:
        q_tokens = _tokens(query)
        if not q_tokens:
            return []
        now = datetime.now(timezone.utc)
        results: list[ScoredMemory] = []
        for m in candidates:
            overlap = len(q_tokens & _tokens(m.content))
            if overlap == 0:
                continue
            relevance = overlap / len(q_tokens)
            conf = self.confidence.decay(m, now)
            results.append(ScoredMemory(m, 0.7 * relevance + 0.3 * conf))
        return results


def _recency_boost(m: Memory, now: datetime, half_life_days: float) -> float:
    age = (now - m.timestamp).total_seconds() / 86400.0
    if age <= 0:
        return 1.0
    return math.pow(0.5, age / max(half_life_days, 1e-9))

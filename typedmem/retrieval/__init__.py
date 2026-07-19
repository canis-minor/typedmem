"""Minimal typed retrieval pipeline (v0, pre-benchmark).

A modular query → typed-routing → typed-filters → vector-candidates →
temporal-resolution → reranking → top-k pipeline. Each stage is importable and
benchmarkable on its own; ``TypedRetriever`` composes them.

Not the final retrieval architecture — deliberately excludes graph traversal,
multi-hop reasoning, LLM reranking, and learned ranking. The point is a clean
baseline for evaluating whether typed retrieval beats vector-only retrieval.
"""

from .filters import RetrievalFilters, apply_filters, build_filters
from .ranker import RankedMemory, RankWeights, rerank
from .resolver import latest_per_slot, remove_superseded, resolve_temporal
from .retriever import TypedRetriever
from .router import DEFAULT_ROUTES, RetrievalIntent, route_query
from .vector_search import Candidate, MemoryVectorizer, search_candidates

__all__ = [
    "Candidate",
    "DEFAULT_ROUTES",
    "MemoryVectorizer",
    "RankWeights",
    "RankedMemory",
    "RetrievalFilters",
    "RetrievalIntent",
    "TypedRetriever",
    "apply_filters",
    "build_filters",
    "latest_per_slot",
    "remove_superseded",
    "rerank",
    "resolve_temporal",
    "route_query",
    "search_candidates",
]

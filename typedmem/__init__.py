"""TypedMemory: contract-driven memory for AI agents.

Four contracts make a typed memory:

- ``DomainProfile`` + ``TypeSpec``    — schema; what types exist, what's required
- ``ConflictPolicy``                  — behaviour; how state changes on slot collision
- ``Source``                          — provenance; structured, with dedup identity
- ``MemoryEvent``                     — evolution; first-class typed change feed

Every write is validated against the profile, resolved per the policy, attributed
to its source, and recorded as an event. Nothing implicit, nothing learned by
magic — the agent's beliefs are auditable because the contracts are explicit.
"""

from .agent import AgentMemory, AgentMemoryReflection
from .embeddings import EmbeddingProvider, HashingEmbeddingProvider, cosine
from .events import EVENT_SOURCES, EventSource, MemoryEvent
from .evolvers import (
    ContradictionSurfacer,
    EvolutionRecord,
    EvolutionResult,
    Evolver,
    GoalResolver,
    PreferenceDriftDetector,
    SummaryEvolver,
    revert_goal_resolution,
)
from .extractor import ExtractionResult, Extractor, LLMExtractor, RuleBasedExtractor
from .llm import AnthropicClient, FakeClient, LLMClient, OpenAIClient
from .policy import (
    DEFAULT_POLICIES,
    ConflictAction,
    ConflictPolicy,
    PolicyEngine,
    TypePolicy,
)
from .profiles import DomainProfile, TypeSpec
from .prompts import PROMPTS
from .retriever import RelevanceWeights, Retriever, ScoredMemory
from .schema import GoalStatus, Memory, MemoryType
from .source import Source
from .stores import (
    InMemoryStore,
    JSONLMemoryStore,
    MemoryStore,
    SQLiteMemoryStore,
)

__version__ = "0.7.0"

__all__ = [
    "DEFAULT_POLICIES",
    "EVENT_SOURCES",
    "AgentMemory",
    "AgentMemoryReflection",
    "AnthropicClient",
    "ConflictAction",
    "ConflictPolicy",
    "ContradictionSurfacer",
    "DomainProfile",
    "EmbeddingProvider",
    "EventSource",
    "EvolutionRecord",
    "EvolutionResult",
    "Evolver",
    "ExtractionResult",
    "Extractor",
    "FakeClient",
    "GoalResolver",
    "GoalStatus",
    "HashingEmbeddingProvider",
    "InMemoryStore",
    "JSONLMemoryStore",
    "LLMClient",
    "LLMExtractor",
    "Memory",
    "MemoryEvent",
    "MemoryStore",
    "MemoryType",
    "OpenAIClient",
    "PROMPTS",
    "PolicyEngine",
    "PreferenceDriftDetector",
    "RelevanceWeights",
    "Retriever",
    "RuleBasedExtractor",
    "ScoredMemory",
    "SQLiteMemoryStore",
    "Source",
    "SummaryEvolver",
    "TypePolicy",
    "TypeSpec",
    "__version__",
    "cosine",
    "revert_goal_resolution",
]

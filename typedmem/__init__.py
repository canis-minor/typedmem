"""TypedMemory: structured, policy-aware memory for AI systems."""

from .agent import AgentMemory, AgentMemoryReflection
from .embeddings import EmbeddingProvider, HashingEmbeddingProvider, cosine
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

__version__ = "0.5.0"

__all__ = [
    "DEFAULT_POLICIES",
    "AgentMemory",
    "AgentMemoryReflection",
    "AnthropicClient",
    "ConflictAction",
    "ConflictPolicy",
    "ContradictionSurfacer",
    "DomainProfile",
    "EmbeddingProvider",
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

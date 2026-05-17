"""Agent-facing memory contract.

``AgentMemory`` is the single front door for agent frameworks to plug into
TypedMemory. It exposes four verbs — ``remember`` / ``recall`` / ``reflect``
/ ``forget`` — over the existing extractor + store + retriever + evolver
primitives. Same library, smaller surface, agent-shaped.

Nothing here is new logic. Everything is a 5-to-30-line wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .embeddings import EmbeddingProvider, HashingEmbeddingProvider
from .evolvers import (
    EvolutionRecord,
    GoalResolver,
    PreferenceDriftDetector,
    SummaryEvolver,
)
from .extractor import Extractor, RuleBasedExtractor
from .llm.base import LLMClient
from .policy import PolicyEngine
from .profiles.base import DomainProfile
from .retriever import Retriever, ScoredMemory
from .schema import Memory
from .source import Source
from .stores import InMemoryStore, MemoryStore, SQLiteMemoryStore


@dataclass
class AgentMemoryReflection:
    """Aggregated result of running every reflection pass.

    Each field is the raw output of one evolver; ``summary()`` collapses to a
    one-line human-readable status for logging/printing.
    """

    contradictions: list[list[Memory]] = field(default_factory=list)
    drift_records: list[EvolutionRecord] = field(default_factory=list)
    goal_records: list[EvolutionRecord] = field(default_factory=list)
    summary_records: list[EvolutionRecord] = field(default_factory=list)

    def summary(self) -> str:
        parts: list[str] = []
        if self.contradictions:
            n = sum(len(c) for c in self.contradictions)
            parts.append(f"{len(self.contradictions)} contradiction cluster(s) covering {n} memories")
        if self.drift_records:
            parts.append(f"{len(self.drift_records)} unstable preference(s)")
        if self.goal_records:
            parts.append(f"{len(self.goal_records)} goal(s) resolved")
        if self.summary_records:
            parts.append(f"{len(self.summary_records)} stale cluster(s) summarized")
        return "; ".join(parts) if parts else "no issues detected"

    def is_empty(self) -> bool:
        return not (
            self.contradictions or self.drift_records
            or self.goal_records or self.summary_records
        )


class AgentMemory:
    """Long-term memory + reflection for one agent.

    Wraps a store, an extractor, a retriever, and the evolver pipeline into
    a four-verb interface — the unit of integration agent frameworks expect.

    ```python
    from typedmem import AgentMemory

    mem = AgentMemory(profile="personal", path="agent.db")
    mem.remember("User wants to learn Rust")
    hits = mem.recall("what does the user want to learn?")
    report = mem.reflect()
    print(report.summary())
    ```

    Everything is opt-in: with no args you get an in-memory store, the
    ``personal`` profile, the zero-dep hashing embedder, and a rule-based
    extractor. Pass ``extractor=LLMExtractor(...)`` for LLM extraction;
    pass ``llm_client=...`` to unlock summarization in ``reflect()``.
    """

    def __init__(
        self,
        *,
        profile: str | DomainProfile | None = "personal",
        path: str | Path = ":memory:",
        workspace: str = "default",
        store: MemoryStore | None = None,
        extractor: Extractor | None = None,
        embedder: EmbeddingProvider | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        # If the caller hands in a pre-built store, defer to it entirely
        # (its policy and profile are authoritative; ignore the profile arg).
        if store is not None:
            self.store = store
            self.profile = getattr(store, "profile", None)
        else:
            self.profile = (
                DomainProfile.builtin(profile) if isinstance(profile, str) else profile
            )
            policy = PolicyEngine.from_profile(self.profile) if self.profile else None
            in_memory = str(path) == ":memory:"
            if in_memory:
                self.store = InMemoryStore(
                    policy=policy,
                    default_workspace=workspace,
                    profile=self.profile,
                )
            else:
                self.store = SQLiteMemoryStore(
                    path,
                    policy=policy,
                    default_workspace=workspace,
                    profile=self.profile,
                )

        self.workspace = workspace
        self.extractor = extractor or RuleBasedExtractor()
        self.embedder = embedder or HashingEmbeddingProvider()
        self.llm_client = llm_client

        # Built lazily on first ``recall`` call.
        self._retriever: Retriever | None = None

    # ── remember ──────────────────────────────────────────────────────────
    def remember(
        self,
        text: str,
        *,
        subject: str | None = None,
        source: Source | None = None,
    ) -> list[Memory]:
        """Extract typed memories from ``text`` and store them.

        Returns the memories that were added (after conflict resolution).
        """
        extracted = self.extractor.extract(
            text,
            subject=subject,
            workspace=self.workspace,
            default_source=source,
        )
        return [self.store.add(m) for m in extracted]

    # ── recall ────────────────────────────────────────────────────────────
    def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        types: list[str] | None = None,
        tags: list[str] | None = None,
        since: datetime | None = None,
        include_superseded: bool = False,
    ) -> list[ScoredMemory]:
        """Semantic + recency + confidence-blended retrieval."""
        if self._retriever is None:
            self._retriever = Retriever(self.store, embedder=self.embedder)
        return self._retriever.relevant(
            query,
            limit=limit,
            types=types,
            tags=tags,
            since=since,
            workspace=self.workspace,
            include_superseded=include_superseded,
        )

    # ── reflect ───────────────────────────────────────────────────────────
    def reflect(
        self,
        *,
        dry_run: bool = False,
        include_summary: bool = False,
        drift_min_replaces: int = 3,
        drift_window_days: float = 30.0,
        goal_threshold: float = 0.85,
    ) -> AgentMemoryReflection:
        """Run the evolver pipeline and return a structured report.

        - ``dry_run=True`` previews changes without mutating the store.
        - ``include_summary=True`` runs the LLM-backed SummaryEvolver
          (requires ``llm_client`` to have been set at construction).
        """
        contradictions = self.store.contradictions(workspace=self.workspace)

        drift = PreferenceDriftDetector(
            min_replaces=drift_min_replaces,
            window_days=drift_window_days,
        ).evolve(self.store, workspace=self.workspace, dry_run=dry_run)

        goals = GoalResolver(self.embedder, threshold=goal_threshold).evolve(
            self.store, workspace=self.workspace, dry_run=dry_run,
        )

        summary_records: list[EvolutionRecord] = []
        if include_summary:
            if self.llm_client is None:
                raise RuntimeError(
                    "reflect(include_summary=True) requires llm_client at construction"
                )
            sr = SummaryEvolver(self.llm_client).evolve(
                self.store, workspace=self.workspace, dry_run=dry_run,
            )
            summary_records = sr.records

        return AgentMemoryReflection(
            contradictions=contradictions,
            drift_records=drift.records,
            goal_records=goals.records,
            summary_records=summary_records,
        )

    # ── forget ────────────────────────────────────────────────────────────
    def forget(self, memory_id: str) -> bool:
        """Explicit deletion. Returns True if the memory existed."""
        return self.store.delete(memory_id)

    # ── housekeeping ──────────────────────────────────────────────────────
    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "AgentMemory":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __len__(self) -> int:
        return sum(
            1 for m in self.store
            if m.workspace == self.workspace and m.superseded_by is None
        )

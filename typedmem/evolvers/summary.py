"""SummaryEvolver: condense stale clusters into a single new memory.

**Non-destructive in v0.4c.** Originals are never modified or superseded —
the new summary memory carries ``metadata["summarizes"] = [ids]`` linking
back. Destructive compaction (actually removing the originals) is deferred
to v0.5 once the audit trail has proven trustworthy in practice.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..kernel import Transition
from ..llm.base import LLMClient
from ..schema import Memory
from ..source import Source
from .base import EvolutionRecord, EvolutionResult

if TYPE_CHECKING:
    from ..stores.base import MemoryStore


_DEFAULT_PROMPT = """\
You are a memory summarizer. Below are several related memories from an AI
system, all about the same subject. They have aged enough that the system
wants a single condensed fact to retain instead of inspecting each one.

Write ONE short sentence (under 25 words) that faithfully summarizes the
group. No prose around it, no quotes — just the sentence.

Subject: {subject}
Type: {type}

Memories:
{memory_lines}
"""


class SummaryEvolver:
    name = "summary_evolver"

    def __init__(
        self,
        client: LLMClient,
        *,
        confidence_floor: float = 0.3,
        min_cluster_size: int = 3,
        target_type: str = "fact",
        cluster_types: tuple[str, ...] = ("event", "observation"),
        prompt_template: str | None = None,
    ) -> None:
        if min_cluster_size < 2:
            raise ValueError("min_cluster_size must be >= 2")
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError("confidence_floor must be in [0, 1]")
        self.client = client
        self.confidence_floor = confidence_floor
        self.min_cluster_size = min_cluster_size
        self.target_type = target_type
        self.cluster_types = cluster_types
        self.prompt_template = prompt_template or _DEFAULT_PROMPT

    def _find_stale_clusters(self, store: "MemoryStore", ws: str) -> list[list[Memory]]:
        """Group by (workspace, type, subject) and keep groups whose decayed
        confidence is below the floor for every member."""
        now = datetime.now(timezone.utc)
        groups: dict[tuple[str, str, str | None], list[Memory]] = defaultdict(list)
        for m in store:
            if m.workspace != ws or m.superseded_by is not None:
                continue
            if m.type not in self.cluster_types:
                continue
            if store.policy.effective_confidence(m, now) >= self.confidence_floor:
                continue
            # Skip memories that are themselves products of summarization,
            # to avoid runaway summarize-of-summaries.
            if "summarizes" in m.metadata:
                continue
            # Skip originals that have already been folded into a summary.
            if m.metadata.get("summarized_by"):
                continue
            groups[(m.workspace, m.type, m.subject)].append(m)
        return [
            sorted(members, key=lambda x: x.timestamp)
            for members in groups.values()
            if len(members) >= self.min_cluster_size
        ]

    def _build_prompt(self, cluster: list[Memory]) -> str:
        lines = "\n".join(
            f"  - ({m.timestamp.date()}) {m.content}" for m in cluster
        )
        return self.prompt_template.format(
            subject=cluster[0].subject or "(none)",
            type=cluster[0].type,
            memory_lines=lines,
        )

    def _merge_sources(self, cluster: list[Memory]) -> list[Source]:
        seen: set = set()
        merged: list[Source] = []
        for m in cluster:
            for s in m.sources:
                k = s.key()
                if k not in seen:
                    seen.add(k)
                    merged.append(s)
        return merged

    def evolve(
        self,
        store: "MemoryStore",
        *,
        workspace: str | None = None,
        dry_run: bool = False,
    ) -> EvolutionResult:
        ws = workspace if workspace is not None else store.default_workspace
        clusters = self._find_stale_clusters(store, ws)
        records: list[EvolutionRecord] = []
        for cluster in clusters:
            input_ids = [m.id for m in cluster]
            if dry_run:
                records.append(EvolutionRecord(
                    evolver=self.name,
                    action="create",
                    input_ids=input_ids,
                    output_ids=[],
                    reason=f"would summarize {len(cluster)} stale memories "
                           f"of type={cluster[0].type} subject={cluster[0].subject!r}",
                ))
                continue
            prompt = self._build_prompt(cluster)
            text = self.client.complete(prompt).strip()
            if not text:
                # The LLM gave us nothing — skip but record the attempt.
                records.append(EvolutionRecord(
                    evolver=self.name,
                    action="create",
                    input_ids=input_ids,
                    output_ids=[],
                    reason="LLM returned empty summary; skipped",
                ))
                continue
            summary = Memory(
                type=self.target_type,
                content=text,
                subject=cluster[0].subject,
                workspace=ws,
                confidence=0.7,
                sources=self._merge_sources(cluster),
                metadata={
                    "summarizes": input_ids,
                    "summarizer": self.name,
                },
            )
            record = EvolutionRecord(
                evolver=self.name,
                action="create",
                input_ids=input_ids,
                output_ids=[summary.id],
                reason=f"summarized {len(cluster)} stale memories into one {self.target_type}",
            )
            records.append(record)
            # Raw create: bypasses conflict resolution AND profile validation on
            # purpose — a profile-bound store might reject ``target_type``, and
            # the summary must not merge into an existing slot. The library owns
            # this memory, so it goes in as-is (v1) through the kernel.
            store.apply_transition(
                Transition(
                    action="create",
                    memory=summary,
                    actor="evolver",
                    actor_name=self.name,
                    evidence=input_ids,
                    reason=record.reason,
                )
            )
            # Forward-link each original to the summary so subsequent runs skip
            # them. Fresh metadata — never mutate the loaded memory in place.
            for m in cluster:
                updated_metadata = {**m.metadata, "summarized_by": summary.id}
                store.apply_transition(
                    Transition(
                        action="annotate",
                        memory_id=m.id,
                        expected_version=m.version,
                        changes={"metadata": updated_metadata},
                        actor="evolver",
                        actor_name=self.name,
                        evidence=[summary.id],
                        reason=f"folded into summary {summary.id}",
                    )
                )
        return EvolutionResult(self.name, records, dry_run)

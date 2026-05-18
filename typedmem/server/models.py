"""Pydantic request/response models for the HTTP server.

Wire format mirrors ``Memory.to_dict()`` and ``MemoryEvent.to_dict()`` so
the Python and HTTP surfaces stay in lock-step. Server-generated fields
(``id``, ``timestamp``, ``updated_at``) are optional on inbound writes —
the store fills them in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceModel(BaseModel):
    """Mirror of typedmem.Source. ``document_id`` is the dedup key."""
    document_id: str
    chunk_id: str | None = None
    span: list[int] | None = None
    uri: str | None = None
    authority: float | None = None
    retrieved_at: datetime | None = None


class MemoryIn(BaseModel):
    """Inbound memory shape for POST /v1/memories. Server fills in id /
    timestamps if omitted, so most clients only need ``type`` + ``content``."""

    model_config = ConfigDict(extra="allow")

    type: str
    content: str
    confidence: float = 1.0
    subject: str | None = None
    tags: list[str] = Field(default_factory=list)
    workspace: str = "default"
    sources: list[SourceModel] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None
    id: str | None = None
    timestamp: datetime | None = None


class MemoryOut(BaseModel):
    """Outbound memory shape: every field round-trips."""

    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    content: str
    confidence: float
    timestamp: datetime
    updated_at: datetime
    subject: str | None = None
    tags: list[str] = Field(default_factory=list)
    workspace: str = "default"
    sources: list[SourceModel] = Field(default_factory=list)
    superseded_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None


EventSourceLiteral = Literal["store", "evolver", "agent", "user", "system"]


class AddRequest(BaseModel):
    """POST /v1/memories body. The ``memory`` field is the actual Memory;
    ``event_source`` / ``event_source_name`` tag the resulting MemoryEvent
    so the caller is identifiable in the timeline (e.g. ``"agent"`` /
    ``"my-bot:v1"``)."""

    memory: MemoryIn
    event_source: EventSourceLiteral = "store"
    event_source_name: str | None = None


class RecallRequest(BaseModel):
    """POST /v1/recall body. Mirrors Retriever.relevant()."""

    query: str
    limit: int = 10
    types: list[str] | None = None
    tags: list[str] | None = None
    since: datetime | None = None
    workspace: str | None = None
    include_superseded: bool = False


class ScoredMemoryOut(BaseModel):
    score: float
    memory: MemoryOut


class MemoryEventOut(BaseModel):
    """Mirror of typedmem.MemoryEvent."""

    id: str
    memory_id: str
    workspace: str
    type: str | None = None
    subject: str | None = None
    action: str
    source: EventSourceLiteral
    source_name: str | None = None
    reason: str = ""
    input_ids: list[str] = Field(default_factory=list)
    output_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class ReflectRequest(BaseModel):
    """POST /v1/reflect — run the evolver pipeline. Mirrors
    AgentMemoryReflection but request-shaped."""

    workspace: str | None = None
    dry_run: bool = False
    drift_min_replaces: int = 3
    drift_window_days: float = 30.0
    goal_threshold: float = 0.85
    # Summary evolver requires an LLM client; not exposed over HTTP for
    # v0.7.0 (caller would need to provide an LLM somehow). Skipped.


class EvolutionRecordOut(BaseModel):
    evolver: str
    action: str
    input_ids: list[str]
    output_ids: list[str]
    reason: str
    timestamp: datetime


class ReflectResponse(BaseModel):
    contradictions: list[list[MemoryOut]]
    drift_records: list[EvolutionRecordOut]
    goal_records: list[EvolutionRecordOut]


class VersionResponse(BaseModel):
    typedmem: str
    instance: str


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: dict[str, Any] = Field(default_factory=dict)

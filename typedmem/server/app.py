"""FastAPI application factory.

The app is shaped as a single factory so callers can pre-build the store +
embedder however they want (different profiles per deployment, in-memory
for tests, SQLite-on-GCS-FUSE for Cloud Run, etc) and just hand the
configured app to uvicorn.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from fastapi import Depends, FastAPI, HTTPException, Path, Query

from .. import __version__ as _typedmem_version
from ..embeddings import EmbeddingProvider, HashingEmbeddingProvider
from ..evolvers import (
    EvolutionRecord,
    GoalResolver,
    PreferenceDriftDetector,
)
from ..events import EventSource
from ..retriever import Retriever
from ..schema import Memory
from ..source import Source
from ..stores.base import MemoryStore
from .auth import make_auth_dependency
from .config import ServerConfig
from .errors import install_error_handlers
from .models import (
    AddRequest,
    ErrorResponse,
    EvolutionRecordOut,
    MemoryEventOut,
    MemoryOut,
    RecallRequest,
    ReflectRequest,
    ReflectResponse,
    ScoredMemoryOut,
    VersionResponse,
)


def _memory_to_out(m: Memory) -> MemoryOut:
    return MemoryOut.model_validate(m.to_dict())


def _event_to_out(e) -> MemoryEventOut:
    return MemoryEventOut.model_validate(e.to_dict())


def _record_to_out(r: EvolutionRecord) -> EvolutionRecordOut:
    return EvolutionRecordOut.model_validate(r.to_dict())


def _memory_from_request(mi) -> Memory:
    """Translate inbound MemoryIn → typedmem.Memory. Drops server-generated
    fields if the client sent them empty; otherwise honours them (lets a
    migrator preserve ids and timestamps)."""
    data = mi.model_dump(exclude_none=True)
    # Pydantic lifts SourceModel into dicts; Memory.from_dict re-hydrates.
    data["sources"] = [Source.from_dict(s) if isinstance(s, dict) else s
                       for s in data.get("sources", [])]
    return Memory.from_dict(data)


def create_app(
    store: MemoryStore,
    *,
    embedder: EmbeddingProvider | None = None,
    config: ServerConfig | None = None,
) -> FastAPI:
    """Build a FastAPI app bound to a specific store + embedder + config.

    The store and embedder are captured by closure — one app instance =
    one store. For multi-tenant deploys, the workspace knob on each
    endpoint provides isolation.
    """
    cfg = config or ServerConfig()
    emb = embedder or HashingEmbeddingProvider()

    app = FastAPI(
        title="TypedMemory",
        version=_typedmem_version,
        description=(
            "Contract-driven memory for AI agents — over HTTP. "
            "Typed schemas, explicit conflict policies, structured provenance, "
            "typed event timeline. "
            "See https://github.com/canis-minor/typedmem"
        ),
    )
    install_error_handlers(app)

    if cfg.cors_origin:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[cfg.cors_origin] if cfg.cors_origin != "*" else ["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    auth_dep = make_auth_dependency(cfg)

    # Single Retriever instance shared across recall requests so the
    # in-memory embedding cache (if any) survives across calls.
    retriever = Retriever(store, embedder=emb)

    # ── unauthenticated routes ───────────────────────────────────────────
    @app.get("/healthz", tags=["ops"])
    async def healthz():
        return {"status": "ok"}

    @app.get("/v1/version", response_model=VersionResponse, tags=["ops"])
    async def version():
        return VersionResponse(typedmem=_typedmem_version, instance=cfg.instance_name)

    # ── authenticated routes ─────────────────────────────────────────────
    @app.post(
        "/v1/memories",
        response_model=MemoryOut,
        responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
        tags=["memories"],
        dependencies=[Depends(auth_dep)],
    )
    async def add_memory(req: AddRequest):
        m = _memory_from_request(req.memory)
        stored = store.add(
            m,
            event_source=req.event_source,
            event_source_name=req.event_source_name,
        )
        return _memory_to_out(stored)

    @app.get(
        "/v1/memories/{memory_id}",
        response_model=MemoryOut,
        responses={404: {"model": ErrorResponse}},
        tags=["memories"],
        dependencies=[Depends(auth_dep)],
    )
    async def get_memory(memory_id: str = Path(...)):
        m = store.get(memory_id)
        if m is None:
            raise HTTPException(status_code=404, detail={
                "error": f"memory {memory_id!r} not found",
                "code": "not_found", "details": {"id": memory_id},
            })
        return _memory_to_out(m)

    @app.delete(
        "/v1/memories/{memory_id}",
        tags=["memories"],
        dependencies=[Depends(auth_dep)],
    )
    async def delete_memory(
        memory_id: str = Path(...),
        event_source: EventSource = Query(default="store"),
        event_source_name: str | None = Query(default=None),
    ):
        ok = store.delete(memory_id, event_source=event_source,
                          event_source_name=event_source_name)
        if not ok:
            raise HTTPException(status_code=404, detail={
                "error": f"memory {memory_id!r} not found",
                "code": "not_found", "details": {"id": memory_id},
            })
        return {"deleted": memory_id}

    @app.get(
        "/v1/memories",
        response_model=list[MemoryOut],
        tags=["memories"],
        dependencies=[Depends(auth_dep)],
    )
    async def list_memories(
        workspace: str | None = Query(default=None),
        type: str | None = Query(default=None),
        include_superseded: bool = Query(default=False),
        limit: int = Query(default=0, ge=0),
    ):
        if type is not None:
            items = store.by_type(type, workspace=workspace,
                                  include_superseded=include_superseded)
        else:
            items = store.all(workspace=workspace,
                              include_superseded=include_superseded)
        items.sort(key=lambda m: m.timestamp, reverse=True)
        if limit:
            items = items[:limit]
        return [_memory_to_out(m) for m in items]

    @app.post(
        "/v1/recall",
        response_model=list[ScoredMemoryOut],
        tags=["recall"],
        dependencies=[Depends(auth_dep)],
    )
    async def recall(req: RecallRequest):
        hits = retriever.relevant(
            req.query,
            limit=req.limit,
            types=req.types,
            tags=req.tags,
            since=req.since,
            workspace=req.workspace,
            include_superseded=req.include_superseded,
        )
        return [
            ScoredMemoryOut(score=h.score, memory=_memory_to_out(h.memory))
            for h in hits
        ]

    @app.get(
        "/v1/memories/{memory_id}/history",
        response_model=list[MemoryEventOut],
        tags=["timeline"],
        dependencies=[Depends(auth_dep)],
    )
    async def memory_history(memory_id: str = Path(...)):
        return [_event_to_out(e) for e in store.history(memory_id)]

    @app.get(
        "/v1/timeline",
        response_model=list[MemoryEventOut],
        tags=["timeline"],
        dependencies=[Depends(auth_dep)],
    )
    async def timeline(
        subject: str | None = Query(default=None),
        type: str | None = Query(default=None),
        workspace: str | None = Query(default=None),
        source: EventSource | None = Query(default=None),
    ):
        events = store.timeline(
            subject=subject, type=type, workspace=workspace, source=source,
        )
        return [_event_to_out(e) for e in events]

    @app.get(
        "/v1/changed-since",
        response_model=list[MemoryEventOut],
        tags=["timeline"],
        dependencies=[Depends(auth_dep)],
    )
    async def changed_since(
        since: datetime = Query(...,
            description="ISO 8601 timestamp; events with timestamp > since are returned"),
    ):
        return [_event_to_out(e) for e in store.changed_since(since)]

    @app.post(
        "/v1/reflect",
        response_model=ReflectResponse,
        tags=["reflect"],
        dependencies=[Depends(auth_dep)],
    )
    async def reflect(req: ReflectRequest):
        contradictions = store.contradictions(workspace=req.workspace)
        drift = PreferenceDriftDetector(
            min_replaces=req.drift_min_replaces,
            window_days=req.drift_window_days,
        ).evolve(store, workspace=req.workspace, dry_run=req.dry_run)
        goals = GoalResolver(emb, threshold=req.goal_threshold).evolve(
            store, workspace=req.workspace, dry_run=req.dry_run,
        )
        return ReflectResponse(
            contradictions=[[_memory_to_out(m) for m in cluster]
                            for cluster in contradictions],
            drift_records=[_record_to_out(r) for r in drift.records],
            goal_records=[_record_to_out(r) for r in goals.records],
        )

    @app.get(
        "/v1/contradictions",
        response_model=list[list[MemoryOut]],
        tags=["reflect"],
        dependencies=[Depends(auth_dep)],
    )
    async def contradictions(
        workspace: str | None = Query(default=None),
    ):
        clusters = store.contradictions(workspace=workspace)
        return [[_memory_to_out(m) for m in cluster] for cluster in clusters]

    @app.get(
        "/v1/workspaces",
        response_model=list[str],
        tags=["ops"],
        dependencies=[Depends(auth_dep)],
    )
    async def workspaces():
        return store.workspaces()

    return app

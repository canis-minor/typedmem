"""SQLite-backed MemoryStore. Stdlib sqlite3 only.

v0.4a schema adds ``sources`` (JSON list), ``workspace``, ``superseded_by``.
The legacy ``source TEXT`` column is retained on existing DBs for read-path
compatibility and is lifted into ``sources`` on first open in pure Python
(no JSON1 dependency).

v0.6a adds a ``memory_events`` table holding the first-class event log,
with indexes on memory_id / workspace / (workspace,type) /
(workspace,type,subject) / timestamp.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..events import EventSource, MemoryEvent
from ..policy import PolicyEngine
from ..schema import GoalStatus, Memory, MemoryType
from ..source import Source
from .base import MemoryStore


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    content       TEXT NOT NULL,
    confidence    REAL NOT NULL,
    timestamp     TEXT NOT NULL,
    subject       TEXT,
    tags          TEXT NOT NULL DEFAULT '[]',
    sources       TEXT NOT NULL DEFAULT '[]',
    workspace     TEXT NOT NULL DEFAULT 'default',
    superseded_by TEXT,
    metadata      TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL,
    status        TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    embedder_id   TEXT,
    embedding     TEXT
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_memories_workspace    ON memories(workspace)",
    "CREATE INDEX IF NOT EXISTS idx_memories_ws_type      ON memories(workspace, type)",
    "CREATE INDEX IF NOT EXISTS idx_memories_ws_type_subj ON memories(workspace, type, subject)",
    "CREATE INDEX IF NOT EXISTS idx_memories_superseded   ON memories(superseded_by)",
]


_CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS memory_events (
    id           TEXT PRIMARY KEY,
    memory_id    TEXT NOT NULL,
    workspace    TEXT NOT NULL,
    type         TEXT,
    subject      TEXT,
    action       TEXT NOT NULL,
    source       TEXT NOT NULL,
    source_name  TEXT,
    reason       TEXT NOT NULL DEFAULT '',
    input_ids    TEXT NOT NULL DEFAULT '[]',
    output_ids   TEXT NOT NULL DEFAULT '[]',
    payload      TEXT NOT NULL DEFAULT '{}',
    timestamp    TEXT NOT NULL
)
"""

_EVENT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_memory_id      ON memory_events(memory_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_workspace      ON memory_events(workspace)",
    "CREATE INDEX IF NOT EXISTS idx_events_ws_type        ON memory_events(workspace, type)",
    "CREATE INDEX IF NOT EXISTS idx_events_ws_type_subj   ON memory_events(workspace, type, subject)",
    "CREATE INDEX IF NOT EXISTS idx_events_timestamp      ON memory_events(timestamp)",
]


# Columns that may be missing on a pre-v0.4a database. The ALTERs run BEFORE
# index creation so v0.4a indexes that mention these columns work on upgrade.
_v04a_COLUMNS: list[tuple[str, str]] = [
    ("sources",       "ALTER TABLE memories ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'"),
    ("workspace",     "ALTER TABLE memories ADD COLUMN workspace TEXT NOT NULL DEFAULT 'default'"),
    ("superseded_by", "ALTER TABLE memories ADD COLUMN superseded_by TEXT"),
    # v0.8 (RFC-0001): optimistic-concurrency version. Old rows migrate to 1.
    ("version",       "ALTER TABLE memories ADD COLUMN version INTEGER NOT NULL DEFAULT 1"),
]


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}

    for col, ddl in _v04a_COLUMNS:
        if col not in existing:
            conn.execute(ddl)

    for stmt in _INDEXES:
        conn.execute(stmt)

    conn.execute(_CREATE_EVENTS_TABLE)
    for stmt in _EVENT_INDEXES:
        conn.execute(stmt)

    # Lift any legacy ``source`` (TEXT, v0.3) into ``sources`` (JSON list).
    # Pure Python — no JSON1 functions needed.
    if "source" in existing:
        legacy_rows = conn.execute(
            "SELECT id, source, updated_at FROM memories "
            "WHERE source IS NOT NULL AND source != '' AND sources = '[]'"
        ).fetchall()
        for row in legacy_rows:
            try:
                retrieved_at = datetime.fromisoformat(row["updated_at"])
            except (TypeError, ValueError):
                retrieved_at = None
            src_kwargs = {"document_id": row["source"]}
            if retrieved_at is not None:
                src_kwargs["retrieved_at"] = retrieved_at
            src = Source(**src_kwargs)
            conn.execute(
                "UPDATE memories SET sources = ? WHERE id = ?",
                (json.dumps([src.to_dict()]), row["id"]),
            )

    conn.commit()


def _row_to_memory(row: sqlite3.Row) -> Memory:
    cols = row.keys()
    sources_json = row["sources"] if "sources" in cols else "[]"
    workspace = row["workspace"] if "workspace" in cols else "default"
    superseded_by = row["superseded_by"] if "superseded_by" in cols else None
    version = row["version"] if "version" in cols and row["version"] is not None else 1

    sources = [Source.from_dict(s) for s in json.loads(sources_json or "[]")]

    m = Memory(
        type=row["type"],
        content=row["content"],
        confidence=row["confidence"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        id=row["id"],
        subject=row["subject"],
        tags=json.loads(row["tags"]),
        sources=sources,
        workspace=workspace,
        superseded_by=superseded_by,
        metadata=json.loads(row["metadata"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        status=row["status"] if row["status"] else None,
        version=version,
    )
    if "embedding" in cols and row["embedding"]:
        m.metadata["_embedding"] = json.loads(row["embedding"])
        m.metadata["_embedder_id"] = row["embedder_id"]
    return m


def _row_to_event(row: sqlite3.Row) -> MemoryEvent:
    return MemoryEvent(
        id=row["id"],
        memory_id=row["memory_id"],
        workspace=row["workspace"],
        type=row["type"],
        subject=row["subject"],
        action=row["action"],
        source=row["source"],
        source_name=row["source_name"],
        reason=row["reason"] or "",
        input_ids=json.loads(row["input_ids"] or "[]"),
        output_ids=json.loads(row["output_ids"] or "[]"),
        payload=json.loads(row["payload"] or "{}"),
        timestamp=datetime.fromisoformat(row["timestamp"]),
    )


class SQLiteMemoryStore(MemoryStore):
    def __init__(
        self,
        path: str | Path = ":memory:",
        policy: PolicyEngine | None = None,
        *,
        default_workspace: str = "default",
        profile=None,
        identity=None,
        confidence=None,
        lifecycle=None,
    ) -> None:
        super().__init__(
            policy, default_workspace=default_workspace, profile=profile,
            identity=identity, confidence=confidence, lifecycle=lifecycle,
        )
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        _ensure_schema(self._conn)

    def close(self) -> None:
        self._conn.close()

    def _put(self, m: Memory) -> None:
        emb = m.metadata.pop("_embedding", None)
        emb_id = m.metadata.pop("_embedder_id", None)
        self._conn.execute(
            """
            INSERT INTO memories
              (id, type, content, confidence, timestamp, subject, tags, sources,
               workspace, superseded_by, metadata, updated_at, status, version,
               embedder_id, embedding)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              type=excluded.type, content=excluded.content,
              confidence=excluded.confidence, timestamp=excluded.timestamp,
              subject=excluded.subject, tags=excluded.tags,
              sources=excluded.sources, workspace=excluded.workspace,
              superseded_by=excluded.superseded_by,
              metadata=excluded.metadata, updated_at=excluded.updated_at,
              status=excluded.status, version=excluded.version,
              embedder_id=COALESCE(excluded.embedder_id, memories.embedder_id),
              embedding=COALESCE(excluded.embedding, memories.embedding)
            """,
            (
                m.id, m.type, m.content, m.confidence,
                m.timestamp.isoformat(), m.subject, json.dumps(m.tags),
                json.dumps([s.to_dict() for s in m.sources]),
                m.workspace, m.superseded_by,
                json.dumps(m.metadata), m.updated_at.isoformat(),
                m.status,                              # already a string
                m.version,
                emb_id, json.dumps(emb) if emb is not None else None,
            ),
        )
        self._conn.commit()
        if emb is not None:
            m.metadata["_embedding"] = emb
            m.metadata["_embedder_id"] = emb_id

    def _get(self, memory_id: str) -> Memory | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return _row_to_memory(row) if row else None

    def _delete(self, memory_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def _iter(self) -> Iterator[Memory]:
        for row in self._conn.execute("SELECT * FROM memories"):
            yield _row_to_memory(row)

    def _append_event(self, event: MemoryEvent) -> None:
        self._conn.execute(
            """
            INSERT INTO memory_events
              (id, memory_id, workspace, type, subject, action,
               source, source_name, reason, input_ids, output_ids, payload, timestamp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.id, event.memory_id, event.workspace, event.type, event.subject,
                event.action, event.source, event.source_name, event.reason,
                json.dumps(event.input_ids), json.dumps(event.output_ids),
                json.dumps(event.payload), event.timestamp.isoformat(),
            ),
        )
        self._conn.commit()

    def _iter_events(self) -> Iterator[MemoryEvent]:
        for row in self._conn.execute("SELECT * FROM memory_events ORDER BY timestamp"):
            yield _row_to_event(row)

    # ── Optimized overrides ──────────────────────────────────────────────
    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def by_type(self, t: str | MemoryType, *, workspace: str | None = None,
                include_superseded: bool = False) -> list[Memory]:
        ws = workspace if workspace is not None else self.default_workspace
        type_str = t.value if isinstance(t, MemoryType) else t
        if include_superseded:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE type=? AND workspace=?",
                (type_str, ws),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE type=? AND workspace=? AND superseded_by IS NULL",
                (type_str, ws),
            ).fetchall()
        return [_row_to_memory(r) for r in rows]

    def workspaces(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT workspace FROM memories ORDER BY workspace"
        ).fetchall()
        return [r["workspace"] for r in rows]

    def _find_same_slot(self, workspace: str, t: str | MemoryType, subject: str) -> Memory | None:
        type_str = t.value if isinstance(t, MemoryType) else t
        row = self._conn.execute(
            "SELECT * FROM memories "
            "WHERE workspace=? AND type=? AND subject=? AND superseded_by IS NULL "
            "LIMIT 1",
            (workspace, type_str, subject),
        ).fetchone()
        return _row_to_memory(row) if row else None

    def history(self, memory_id: str) -> list[MemoryEvent]:
        self._migrate_legacy_history(memory_id)
        rows = self._conn.execute(
            "SELECT * FROM memory_events WHERE memory_id=? ORDER BY timestamp",
            (memory_id,),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def timeline(
        self,
        *,
        subject: str | None = None,
        type: str | None = None,
        workspace: str | None = None,
        source: EventSource | None = None,
    ) -> list[MemoryEvent]:
        from ..events import EVENT_SOURCES
        type_str = type.value if isinstance(type, MemoryType) else type
        if source is not None and source not in EVENT_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(EVENT_SOURCES)}, got {source!r}"
            )
        self._migrate_legacy_history_all()
        where: list[str] = []
        params: list = []
        if subject is not None:
            where.append("subject=?")
            params.append(subject)
        if type_str is not None:
            where.append("type=?")
            params.append(type_str)
        if workspace is not None:
            where.append("workspace=?")
            params.append(workspace)
        if source is not None:
            where.append("source=?")
            params.append(source)
        sql = "SELECT * FROM memory_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY timestamp"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_event(r) for r in rows]

    def changed_since(self, timestamp: datetime) -> list[MemoryEvent]:
        self._migrate_legacy_history_all()
        rows = self._conn.execute(
            "SELECT * FROM memory_events WHERE timestamp > ? ORDER BY timestamp",
            (timestamp.isoformat(),),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    @classmethod
    def for_profile(cls, profile, path: str | Path = ":memory:", **kwargs) -> "SQLiteMemoryStore":
        """Construct a store bound to a profile with matching policies."""
        return cls(path, policy=PolicyEngine.from_profile(profile), profile=profile, **kwargs)

    def set_embedding(self, memory_id: str, vector: list[float], embedder_id: str) -> None:
        self._conn.execute(
            "UPDATE memories SET embedding=?, embedder_id=? WHERE id=?",
            (json.dumps(vector), embedder_id, memory_id),
        )
        self._conn.commit()

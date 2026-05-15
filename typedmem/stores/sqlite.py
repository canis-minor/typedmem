"""SQLite-backed MemoryStore. Stdlib sqlite3 only.

v0.4a schema adds ``sources`` (JSON list), ``workspace``, ``superseded_by``.
The legacy ``source TEXT`` column is retained on existing DBs for read-path
compatibility and is lifted into ``sources`` on first open in pure Python
(no JSON1 dependency).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator

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


# Columns that may be missing on a pre-v0.4a database. The ALTERs run BEFORE
# index creation so v0.4a indexes that mention these columns work on upgrade.
_v04a_COLUMNS: list[tuple[str, str]] = [
    ("sources",       "ALTER TABLE memories ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'"),
    ("workspace",     "ALTER TABLE memories ADD COLUMN workspace TEXT NOT NULL DEFAULT 'default'"),
    ("superseded_by", "ALTER TABLE memories ADD COLUMN superseded_by TEXT"),
]


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}

    for col, ddl in _v04a_COLUMNS:
        if col not in existing:
            conn.execute(ddl)

    for stmt in _INDEXES:
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
    )
    if "embedding" in cols and row["embedding"]:
        m.metadata["_embedding"] = json.loads(row["embedding"])
        m.metadata["_embedder_id"] = row["embedder_id"]
    return m


class SQLiteMemoryStore(MemoryStore):
    def __init__(
        self,
        path: str | Path = ":memory:",
        policy: PolicyEngine | None = None,
        *,
        default_workspace: str = "default",
        profile=None,
    ) -> None:
        super().__init__(policy, default_workspace=default_workspace, profile=profile)
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
               workspace, superseded_by, metadata, updated_at, status,
               embedder_id, embedding)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              type=excluded.type, content=excluded.content,
              confidence=excluded.confidence, timestamp=excluded.timestamp,
              subject=excluded.subject, tags=excluded.tags,
              sources=excluded.sources, workspace=excluded.workspace,
              superseded_by=excluded.superseded_by,
              metadata=excluded.metadata, updated_at=excluded.updated_at,
              status=excluded.status,
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

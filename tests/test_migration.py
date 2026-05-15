"""v0.3 → v0.4a migration: opening an old SQLite DB and an old JSONL file
should lift legacy ``source`` strings into structured ``Source`` objects."""

import json
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path

from typed_memory import JSONLMemoryStore, MemoryType, SQLiteMemoryStore


# ── SQLite ───────────────────────────────────────────────────────────────────
def _make_v03_sqlite(path: Path) -> str:
    """Build a v0.3-shaped DB by hand. The v0.4a opener will migrate it."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            confidence REAL NOT NULL,
            timestamp TEXT NOT NULL,
            subject TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            status TEXT,
            embedder_id TEXT,
            embedding TEXT
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO memories (id, type, content, confidence, timestamp, source, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("mem-1", "fact", "born 2024", 0.95, now, "design_doc.md", now),
    )
    conn.commit()
    conn.close()
    return now


def test_sqlite_v03_opens_under_v04a(tmp_path: Path):
    path = tmp_path / "old.db"
    _make_v03_sqlite(path)

    with SQLiteMemoryStore(path) as s:
        m = s.get("mem-1")
        assert m is not None
        assert m.workspace == "default"          # ALTER added column with default
        assert m.superseded_by is None
        assert len(m.sources) == 1               # legacy source lifted
        assert m.sources[0].document_id == "design_doc.md"
        assert m.sources[0].authority == 1.0


def test_sqlite_migration_is_idempotent(tmp_path: Path):
    path = tmp_path / "old.db"
    _make_v03_sqlite(path)
    with SQLiteMemoryStore(path):
        pass  # first migration
    # Second open should be a no-op — and not double-lift.
    with SQLiteMemoryStore(path) as s:
        m = s.get("mem-1")
        assert len(m.sources) == 1


def test_sqlite_fresh_v04a_db(tmp_path: Path):
    path = tmp_path / "new.db"
    with SQLiteMemoryStore(path):
        pass
    # All v0.4a columns must exist.
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
    conn.close()
    assert {"sources", "workspace", "superseded_by"} <= cols


# ── JSONL ────────────────────────────────────────────────────────────────────
def test_jsonl_v03_records_lift_source_string(tmp_path: Path):
    path = tmp_path / "old.jsonl"
    # Hand-crafted v0.3 record: source is a string.
    now = datetime.now(timezone.utc).isoformat()
    rec = {
        "id": "mem-2", "type": "fact", "content": "x",
        "confidence": 0.9, "timestamp": now, "updated_at": now,
        "source": "doc.md", "tags": [], "metadata": {},
    }
    path.write_text(json.dumps(rec) + "\n")

    s = JSONLMemoryStore(path)
    m = s.get("mem-2")
    assert m is not None
    assert m.workspace == "default"
    assert len(m.sources) == 1 and m.sources[0].document_id == "doc.md"


def test_memory_kwarg_source_deprecated(recwarn):
    """v0.3 callers that pass source='rule' still work but get a warning."""
    from typed_memory import Memory
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = Memory(MemoryType.FACT, "x", source="rule")
    assert any(issubclass(warning.category, DeprecationWarning) for warning in w)
    assert m.source is None  # lifted and cleared
    assert len(m.sources) == 1 and m.sources[0].document_id == "rule"

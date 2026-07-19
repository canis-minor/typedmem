"""Append-only JSONL store with last-write-wins on memory id.

Writes are append-only so the file is crash-safe and `tail -f`-able. On load,
later records overwrite earlier ones with the same id; deletes are recorded as
tombstones `{"_op": "delete", "id": ...}`. Call ``compact()`` to rewrite the
file to a single line per live memory.

v0.6a adds a sidecar ``.events.jsonl`` file holding the MemoryEvent log.
The two files stay independent: events are never compacted (the timeline is
the historical record), so even a compacted memory file keeps full history."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterator

from ..events import MemoryEvent
from ..policy import PolicyEngine
from ..schema import Memory
from .base import MemoryStore


def _events_path(path: Path) -> Path:
    return path.with_name(path.name + ".events.jsonl")


class JSONLMemoryStore(MemoryStore):
    def __init__(
        self,
        path: str | Path,
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
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path = _events_path(self.path)
        self._items: dict[str, Memory] = {}
        self._events: list[MemoryEvent] = []
        self._load()
        self._load_events()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate partial lines from a crashed write
                if rec.get("_op") == "delete":
                    self._items.pop(rec.get("id"), None)
                else:
                    m = Memory.from_dict(rec)
                    self._items[m.id] = m

    def _load_events(self) -> None:
        if not self.events_path.exists():
            return
        with self.events_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    self._events.append(MemoryEvent.from_dict(rec))
                except (TypeError, ValueError):
                    continue

    def _append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record))
            fh.write("\n")

    def _put(self, m: Memory) -> None:
        self._items[m.id] = m
        self._append(m.to_dict())

    def _get(self, memory_id: str) -> Memory | None:
        return self._items.get(memory_id)

    def _delete(self, memory_id: str) -> bool:
        if memory_id not in self._items:
            return False
        del self._items[memory_id]
        self._append({"_op": "delete", "id": memory_id})
        return True

    def _iter(self) -> Iterator[Memory]:
        return iter(self._items.values())

    def _append_event(self, event: MemoryEvent) -> None:
        self._events.append(event)
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict()))
            fh.write("\n")

    def _iter_events(self) -> Iterator[MemoryEvent]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._items)

    def compact(self) -> None:
        """Rewrite the memory file as one record per live memory. Atomic via
        rename. Events are intentionally NOT compacted — the timeline is the
        historical record."""
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=self.path.name + ".", dir=str(self.path.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                for m in self._items.values():
                    fh.write(json.dumps(m.to_dict()))
                    fh.write("\n")
            os.replace(tmp_path, self.path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

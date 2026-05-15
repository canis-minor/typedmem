"""In-process MemoryStore. Nothing is persisted."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..schema import Memory
from .base import MemoryStore


class InMemoryStore(MemoryStore):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._items: dict[str, Memory] = {}

    def _put(self, m: Memory) -> None:
        self._items[m.id] = m

    def _get(self, memory_id: str) -> Memory | None:
        return self._items.get(memory_id)

    def _delete(self, memory_id: str) -> bool:
        return self._items.pop(memory_id, None) is not None

    def _iter(self) -> Iterator[Memory]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def to_json(self) -> str:
        return json.dumps([m.to_dict() for m in self._items.values()], indent=2)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

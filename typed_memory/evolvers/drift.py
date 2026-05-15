"""PreferenceDriftDetector: meta-memory over REPLACE history.

Each REPLACE writes a timestamp to ``metadata["replace_log"]`` (capped at 20).
This evolver scans memories whose log indicates frequent churn within a
trailing window and annotates them with a ``drift_flags`` entry. The
annotation is the signal; it does NOT create a separate ``concern`` memory
in v0.4c (deferred until profiles can declare their preferred drift output
type).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .base import EvolutionRecord, EvolutionResult, annotate_history, _now

if TYPE_CHECKING:
    from ..stores.base import MemoryStore


class PreferenceDriftDetector:
    name = "preference_drift_detector"

    def __init__(
        self,
        *,
        min_replaces: int = 3,
        window_days: float = 30.0,
        types: tuple[str, ...] | None = None,    # None = any type with replace_log
    ) -> None:
        if min_replaces < 1:
            raise ValueError("min_replaces must be >= 1")
        if window_days <= 0:
            raise ValueError("window_days must be positive")
        self.min_replaces = min_replaces
        self.window_days = window_days
        self.types = types

    def _recent_replaces(self, memory, now: datetime) -> list[datetime]:
        log = memory.metadata.get("replace_log", [])
        cutoff = now - timedelta(days=self.window_days)
        out: list[datetime] = []
        for entry in log:
            try:
                t = datetime.fromisoformat(entry)
            except (TypeError, ValueError):
                continue
            if t >= cutoff:
                out.append(t)
        return out

    def evolve(
        self,
        store: "MemoryStore",
        *,
        workspace: str | None = None,
        dry_run: bool = False,
    ) -> EvolutionResult:
        ws = workspace if workspace is not None else store.default_workspace
        now = _now()
        records: list[EvolutionRecord] = []
        for m in store:
            if m.workspace != ws:
                continue
            if self.types is not None and m.type not in self.types:
                continue
            if not m.metadata.get("replace_log"):
                continue
            recent = self._recent_replaces(m, now)
            if len(recent) < self.min_replaces:
                continue
            reason = (
                f"{m.type}[{m.subject}] changed {len(recent)}× in last "
                f"{self.window_days:.0f}d (total replace_count="
                f"{m.metadata.get('replace_count', '?')})"
            )
            record = EvolutionRecord(
                evolver=self.name,
                action="annotate",
                input_ids=[m.id],
                output_ids=[m.id],
                reason=reason,
            )
            records.append(record)
            if not dry_run:
                flags = m.metadata.setdefault("drift_flags", [])
                flags.append({
                    "evolver": self.name,
                    "at": now.isoformat(),
                    "recent_replaces": len(recent),
                    "window_days": self.window_days,
                })
                annotate_history(m, record)
                m.touch()
                store._put(m)
        return EvolutionResult(self.name, records, dry_run)

"""Policy engine: per-type rules for decay, conflict resolution, and lifecycle.

The default conflict policies below are **provisional**. They make personal-
memory cases work the way v0.1–v0.3 always did, but they are not authoritative
for domain use — a contract-analysis agent will want ``claim`` types with
KEEP_BOTH semantics, a design-review agent will want SUPERSEDE on
``decision``, etc. The v0.4b ``DomainProfile`` system is where those choices
get expressed cleanly. Until then, override per-type via the ``policies`` dict
passed to ``PolicyEngine``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .schema import GoalStatus, Memory, MemoryType
from .source import Source


class ConflictPolicy(str, Enum):
    REPLACE   = "replace"     # existing → updated in place; new memory inherits old id
    KEEP_BOTH = "keep_both"   # both stored independently; no link
    SUPERSEDE = "supersede"   # new inserted; old.superseded_by = new.id; both retained
    REINFORCE = "reinforce"   # single record; sources extended; confidence boosted
    FLAG      = "flag"        # both stored; both metadata["conflicts_with"] points to other
    IGNORE    = "ignore"      # incoming discarded; existing untouched


@dataclass
class ConflictAction:
    policy: ConflictPolicy
    notes: str = ""


@dataclass(frozen=True)
class TypePolicy:
    half_life_days: float | None
    summarizable: bool
    conflict_policy: ConflictPolicy

    # Back-compat: derived from conflict_policy for callers that still ask.
    # Removed in v0.5 alongside PolicyEngine.should_replace.
    @property
    def updatable(self) -> bool:
        return self.conflict_policy in {
            ConflictPolicy.REPLACE,
            ConflictPolicy.REINFORCE,
            ConflictPolicy.SUPERSEDE,
        }


# Keyed by string type names so domain profiles can add their own types
# (claim, evidence, decision, …) without forking. MemoryType-keyed dicts
# are also accepted for back-compat — see ``PolicyEngine.__init__``.
DEFAULT_POLICIES: dict[str, TypePolicy] = {
    "fact":        TypePolicy(None,  False, ConflictPolicy.KEEP_BOTH),
    "preference":  TypePolicy(60.0,  False, ConflictPolicy.REPLACE),
    "goal":        TypePolicy(None,  False, ConflictPolicy.REPLACE),
    "event":       TypePolicy(14.0,  True,  ConflictPolicy.KEEP_BOTH),
    "observation": TypePolicy(7.0,   True,  ConflictPolicy.KEEP_BOTH),
}


def _normalize_keys(policies: dict) -> dict[str, TypePolicy]:
    """Accept either str or MemoryType keys; canonicalize to str."""
    return {(k.value if isinstance(k, Enum) else k): v for k, v in policies.items()}


class PolicyEngine:
    def __init__(
        self,
        policies: dict[str, TypePolicy] | dict[MemoryType, TypePolicy] | None = None,
        *,
        default: TypePolicy | None = None,
    ) -> None:
        self.policies = _normalize_keys(policies) if policies else dict(DEFAULT_POLICIES)
        self._default = default

    @classmethod
    def from_profile(cls, profile, *, default: TypePolicy | None = None) -> "PolicyEngine":
        """Build an engine from a ``DomainProfile``'s effective type map."""
        return cls(profile.policies(), default=default)

    def policy_for(self, t: str | MemoryType) -> TypePolicy:
        key = t.value if isinstance(t, Enum) else t
        if key in self.policies:
            return self.policies[key]
        if self._default is not None:
            return self._default
        raise KeyError(
            f"no policy registered for type {key!r}; "
            f"known: {sorted(self.policies)}"
        )

    # ── confidence decay (unchanged from v0.3) ────────────────────────────
    def effective_confidence(self, m: Memory, now: datetime | None = None) -> float:
        policy = self.policy_for(m.type)
        if policy.half_life_days is None:
            return m.confidence
        now = now or datetime.now(timezone.utc)
        age_days = (now - m.timestamp).total_seconds() / 86400.0
        if age_days <= 0:
            return m.confidence
        decay = math.pow(0.5, age_days / policy.half_life_days)
        return m.confidence * decay

    # ── conflict resolution (new in v0.4a) ────────────────────────────────
    def resolve(self, existing: Memory, incoming: Memory) -> ConflictAction:
        """Decide how to merge ``incoming`` into the store given ``existing``
        already occupies the same slot."""
        if existing.type != incoming.type:
            # Different types in the same (workspace, subject) slot aren't a
            # real conflict — fall through to side-by-side storage.
            return ConflictAction(ConflictPolicy.KEEP_BOTH, "type mismatch")

        policy = self.policy_for(existing.type).conflict_policy

        if policy is ConflictPolicy.REPLACE:
            # Weaker incoming should not displace stronger existing.
            # REINFORCE is exempt — the whole point is to accumulate
            # corroborating evidence regardless of its individual strength.
            if (incoming.timestamp < existing.timestamp
                    or incoming.confidence < existing.confidence):
                return ConflictAction(
                    ConflictPolicy.IGNORE,
                    "incoming weaker than existing for replace",
                )

        return ConflictAction(policy)

    def reinforce_confidence(
        self,
        c_old: float,
        c_new: float,
        new_sources: list[Source],
    ) -> float:
        """Provisional reinforcement blend.

        Each new corroboration closes part of the gap to 1.0, scaled by the
        new source's confidence and authority. Documented as v0.4a-provisional
        — override on a subclass when better numbers exist.
        """
        weight = sum(s.authority for s in new_sources) or 1.0
        bump = c_new * weight * 0.5
        return min(1.0, c_old + (1.0 - c_old) * bump)

    # ── back-compat ───────────────────────────────────────────────────────
    def should_replace(self, existing: Memory, incoming: Memory) -> bool:
        """Deprecated in v0.4a; use ``resolve()`` instead. Removed in v0.5."""
        return self.resolve(existing, incoming).policy == ConflictPolicy.REPLACE

    def is_active(self, m: Memory) -> bool:
        if m.superseded_by is not None:
            return False
        if m.type == MemoryType.GOAL:
            return m.status == GoalStatus.ACTIVE
        return True

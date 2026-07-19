"""TypedMem kernel (RFC-0001): the small, deterministic core that separates
stable engineering abstractions from replaceable domain policies.

The kernel's job is narrow and permanent:

* ``Transition``        — an explicit, inert description of intent to change state.
* ``TransitionEngine``  — the **canonical mutation path for store operations**.
  Every public ``add`` / ``delete`` and every conflict resolution flows through
  ``apply()``: validation, optimistic concurrency (``expected_version``),
  conflict dispatch, version bump, event emission, and persistence.

  NOTE: this is not yet the *only* mutator — evolvers (GoalResolver,
  PreferenceDriftDetector, SummaryEvolver) still use the legacy internal
  ``store._put`` path and will be migrated to Transitions in a follow-up. The
  "single mutation funnel" is the destination that increment reaches, not an
  invariant enforced today.

Replaceable behavior lives behind strategies, each with a default that reproduces
the historical (pre-v0.8) behavior byte-for-byte:

* ``IdentityStrategy``   — how a memory's dedup/slot identity is computed. Active.
* ``ConfidenceStrategy`` — governs confidence *reinforcement* on the mutation
  path today; decay (a read-path calc in ``PolicyEngine.effective_confidence``)
  is NOT yet routed through it. See ``ConfidenceStrategy`` below.
* ``LifecycleStrategy``  — PROVISIONAL / experimental: defined and attached to
  the store, but not yet consulted for lifecycle validation. Injecting one does
  not change behavior yet.

Version invariant (v0.8): a freshly inserted record begins at version 1; every
successful mutation of an existing record increments its version exactly once;
a rejected transition (e.g. an ``expected_version`` mismatch) changes no version.
The emitted ``MemoryEvent`` records the resulting version in ``payload["version"]``.

Nothing here imports the concrete stores at module load; the engine talks to a
store only through its primitives (``_put`` / ``_get`` / ``_delete`` /
``_append_event`` / ``_iter``), so there is no import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .policy import ConflictAction, ConflictPolicy, PolicyEngine
from .schema import GoalStatus, Memory, MemoryType
from .source import Source

if TYPE_CHECKING:
    from .stores.base import MemoryStore


class ConcurrencyError(RuntimeError):
    """Raised when a Transition's ``expected_version`` does not match the
    stored memory's current version — an optimistic-concurrency conflict."""


# ── Strategies ────────────────────────────────────────────────────────────
class IdentityStrategy:
    """Computes the identity key that decides whether two memories occupy the
    same slot (and therefore collide). Replaceable per profile."""

    def key_for(self, m: Memory) -> tuple:
        raise NotImplementedError


class SlotIdentityStrategy(IdentityStrategy):
    """Default identity: ``(workspace, type, subject)`` — exactly the historical
    ``_find_same_slot`` key. Subject-less memories key to ``subject=None`` and,
    under this default, never collide (see ``MemoryStore.find_slot``)."""

    def key_for(self, m: Memory) -> tuple:
        return (m.workspace, m.type, m.subject)


class ConfidenceStrategy:
    """How confidence evolves. Split from the kernel so research can swap the
    numbers without touching the mutation machinery.

    Boundary (v0.8): ``reinforce`` IS active — the TransitionEngine's REINFORCE
    branch calls it. ``decay`` is defined here but the read-path callers
    (retriever, summary) still call ``PolicyEngine.effective_confidence``
    directly; routing decay through the strategy is a follow-up."""

    def reinforce(self, c_old: float, c_new: float, new_sources: list[Source]) -> float:
        raise NotImplementedError

    def decay(self, m: Memory, now: datetime | None = None) -> float:
        raise NotImplementedError


class PolicyConfidenceStrategy(ConfidenceStrategy):
    """Default: delegate to the ``PolicyEngine`` formulas, so existing behavior
    (and ``test_policy`` / ``test_conflicts``) is preserved exactly."""

    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy

    def reinforce(self, c_old: float, c_new: float, new_sources: list[Source]) -> float:
        return self.policy.reinforce_confidence(c_old, c_new, new_sources)

    def decay(self, m: Memory, now: datetime | None = None) -> float:
        return self.policy.effective_confidence(m, now)


class LifecycleStrategy:
    """Legal statuses for a memory and what counts as "active". Lifecycle is a
    policy concern, not a kernel concern — goals, decisions, and preferences
    each want different chains.

    PROVISIONAL (v0.8): defined and attached to the store, but not yet
    consulted for lifecycle validation or transitions — ``Memory.__post_init__``
    and ``PolicyEngine.is_active`` still own that behavior. Injecting a custom
    strategy does NOT change behavior today; wiring is a follow-up increment."""

    def initial_status(self, m: Memory) -> str | None:
        return m.status

    def is_active(self, m: Memory) -> bool:
        return m.superseded_by is None


class DefaultLifecycleStrategy(LifecycleStrategy):
    """Default: reproduces today's goal lifecycle (goals default to ACTIVE;
    a goal is active only while its status is ACTIVE and it is not superseded).
    Mirrors ``Memory.__post_init__`` and ``PolicyEngine.is_active``."""

    def initial_status(self, m: Memory) -> str | None:
        if m.type == MemoryType.GOAL and m.status is None:
            return GoalStatus.ACTIVE.value
        return m.status

    def is_active(self, m: Memory) -> bool:
        if m.superseded_by is not None:
            return False
        if m.type == MemoryType.GOAL:
            return m.status == GoalStatus.ACTIVE
        return True


# ── Transition primitive ──────────────────────────────────────────────────
@dataclass
class Transition:
    """An explicit description of intent to change stored state. A Transition
    does NOT modify anything by itself — only ``TransitionEngine.apply`` does.

    ``action`` is one of ``"add"`` / ``"delete"`` / ``"update"`` (and named
    update variants like ``"change_status"``). For ``"add"`` the whole incoming
    ``memory`` is carried; for ``"update"``/``"delete"`` the target is
    ``memory_id`` and ``changes`` holds the field-level intent. ``expected_version``
    enables optimistic concurrency: when set, the engine refuses the transition
    if the stored version has moved.
    """

    action: str
    memory_id: str | None = None
    expected_version: int | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    actor: str = "store"          # maps to MemoryEvent.source (EventSource)
    actor_name: str | None = None  # maps to MemoryEvent.source_name
    evidence: list[str] = field(default_factory=list)
    reason: str = ""
    memory: Memory | None = None   # payload for action="add"


@dataclass
class TransitionResult:
    """Outcome of applying a Transition. ``memory`` is the resulting record
    (or ``None`` for a delete); ``applied`` is False when the engine declined
    (e.g. IGNORE or a not-found delete)."""

    memory: Memory | None
    applied: bool
    action: str
    reason: str = ""


# ── Transition engine ─────────────────────────────────────────────────────
class TransitionEngine:
    """The single funnel through which stored memories change. Holds only a
    reference to its store and reaches state exclusively via store primitives.
    """

    def __init__(self, store: "MemoryStore") -> None:
        self.store = store

    # -- dispatch -----------------------------------------------------------
    def apply(self, t: Transition):
        if t.action == "add":
            return self._apply_add(t)
        if t.action == "create":
            return self._apply_create(t)
        if t.action == "delete":
            return self._apply_delete(t)
        return self._apply_update(t)

    # -- event emission (single source of truth, reused from the store) -----
    def _emit(
        self,
        m: Memory,
        *,
        action: str,
        input_ids: list[str],
        output_ids: list[str],
        reason: str,
        actor: str,
        actor_name: str | None,
    ) -> None:
        # Lazy import avoids an import cycle (base imports this module at load).
        from .stores.base import _record_lifecycle_event

        _record_lifecycle_event(
            self.store, m,
            action=action, input_ids=input_ids, output_ids=output_ids,
            reason=reason, source=actor, source_name=actor_name,
        )

    # -- add ---------------------------------------------------------------
    def _apply_add(self, t: Transition) -> Memory:
        store = self.store
        m = t.memory
        assert m is not None, "add transition requires a memory"

        existing = store.find_slot(m)
        if existing is None:
            store._put(m)
            self._emit(
                m, action="added", input_ids=[m.id], output_ids=[m.id],
                reason="", actor=t.actor, actor_name=t.actor_name,
            )
            return m

        action = store.policy.resolve(existing, m)
        return self._apply_conflict(
            existing, m, action, actor=t.actor, actor_name=t.actor_name,
        )

    # -- create ------------------------------------------------------------
    def _apply_create(self, t: Transition) -> Memory:
        """Raw insert of a NEW memory, bypassing identity/conflict resolution
        AND profile validation. Used by plugins (e.g. SummaryEvolver) that
        generate library-side memories which must neither be merged into an
        existing slot nor rejected by a domain profile. The record begins at
        version 1; ``evidence`` becomes the event's input_ids."""
        store = self.store
        m = t.memory
        assert m is not None, "create transition requires a memory"
        store._put(m)
        self._emit(
            m, action="create",
            input_ids=list(t.evidence) or [m.id], output_ids=[m.id],
            reason=t.reason, actor=t.actor, actor_name=t.actor_name,
        )
        return m

    # -- delete ------------------------------------------------------------
    def _apply_delete(self, t: Transition) -> bool:
        store = self.store
        existing = store._get(t.memory_id)
        if existing is None:
            return False
        # Emit BEFORE removal so the event survives in the log.
        self._emit(
            existing, action="deleted", input_ids=[t.memory_id], output_ids=[],
            reason=t.reason, actor=t.actor, actor_name=t.actor_name,
        )
        return store._delete(t.memory_id)

    # -- generic update (basis for evolver-driven Transitions) -------------
    def _apply_update(self, t: Transition) -> Memory:
        store = self.store
        m = store._get(t.memory_id)
        if m is None:
            raise KeyError(f"no memory with id {t.memory_id!r}")
        if t.expected_version is not None and m.version != t.expected_version:
            raise ConcurrencyError(
                f"expected version {t.expected_version} for {t.memory_id!r}, "
                f"but stored version is {m.version}"
            )
        for key, value in t.changes.items():
            setattr(m, key, value)
        m.version += 1
        m.touch()
        # Evidence (e.g. the memory ids that justified an evolver's change) is
        # recorded in the event's input_ids alongside the target, matching the
        # legacy annotate_history audit shape.
        input_ids = [m.id, *t.evidence] if t.evidence else [m.id]
        self._emit(
            m, action=t.action, input_ids=input_ids, output_ids=[m.id],
            reason=t.reason, actor=t.actor, actor_name=t.actor_name,
        )
        store._put(m)
        return m

    # -- conflict dispatch (moved verbatim from MemoryStore._apply_conflict,
    #    now the only place stored memories are mutated on collision) -------
    def _apply_conflict(
        self,
        existing: Memory,
        incoming: Memory,
        action: ConflictAction,
        *,
        actor: str = "store",
        actor_name: str | None = None,
    ) -> Memory:
        store = self.store
        p = action.policy

        if p is ConflictPolicy.IGNORE:
            return existing

        if p is ConflictPolicy.KEEP_BOTH:
            store._put(incoming)
            self._emit(
                incoming, action="added",
                input_ids=[incoming.id], output_ids=[incoming.id],
                reason="kept-both alongside existing",
                actor=actor, actor_name=actor_name,
            )
            return incoming

        if p is ConflictPolicy.REPLACE:
            old_content = existing.content
            existing.content = incoming.content
            existing.confidence = incoming.confidence
            existing.timestamp = incoming.timestamp
            existing.tags = list({*existing.tags, *incoming.tags})
            if incoming.sources:
                existing.sources = list(incoming.sources)
            existing.metadata = {**existing.metadata, **incoming.metadata}
            from datetime import timezone
            log = existing.metadata.setdefault("replace_log", [])
            log.append(datetime.now(timezone.utc).isoformat())
            if len(log) > 20:
                del log[:-20]
            existing.metadata["replace_count"] = existing.metadata.get("replace_count", 0) + 1
            existing.touch()
            existing.version += 1
            self._emit(
                existing, action="replaced",
                input_ids=[existing.id], output_ids=[existing.id],
                reason=f"content updated (was: {old_content[:60]!r})",
                actor=actor, actor_name=actor_name,
            )
            store._put(existing)
            return existing

        if p is ConflictPolicy.SUPERSEDE:
            existing.superseded_by = incoming.id
            existing.touch()
            existing.version += 1
            self._emit(
                existing, action="superseded",
                input_ids=[existing.id], output_ids=[incoming.id],
                reason=f"superseded by new {incoming.type}",
                actor=actor, actor_name=actor_name,
            )
            self._emit(
                incoming, action="supersedes",
                input_ids=[existing.id, incoming.id], output_ids=[incoming.id],
                reason=f"supersedes earlier {existing.type}: {existing.content[:60]!r}",
                actor=actor, actor_name=actor_name,
            )
            store._put(existing)
            store._put(incoming)
            return incoming

        if p is ConflictPolicy.REINFORCE:
            seen = {s.key() for s in existing.sources}
            new_unique = [s for s in incoming.sources if s.key() not in seen]
            existing.sources.extend(new_unique)
            existing.confidence = store.confidence.reinforce(
                existing.confidence, incoming.confidence, new_unique or incoming.sources,
            )
            existing.tags = list({*existing.tags, *incoming.tags})
            if incoming.confidence > existing.confidence:
                existing.content = incoming.content
            existing.touch()
            existing.version += 1
            if new_unique:
                src_ids = ", ".join(s.document_id for s in new_unique)
                self._emit(
                    existing, action="reinforced",
                    input_ids=[existing.id], output_ids=[existing.id],
                    reason=f"+{len(new_unique)} source(s): {src_ids}",
                    actor=actor, actor_name=actor_name,
                )
            store._put(existing)
            return existing

        if p is ConflictPolicy.FLAG:
            existing.metadata.setdefault("conflicts_with", []).append(incoming.id)
            incoming.metadata.setdefault("conflicts_with", []).append(existing.id)
            existing.touch()
            existing.version += 1
            self._emit(
                existing, action="flagged",
                input_ids=[existing.id, incoming.id], output_ids=[existing.id],
                reason=f"cross-linked to new {incoming.type}: {incoming.content[:60]!r}",
                actor=actor, actor_name=actor_name,
            )
            self._emit(
                incoming, action="flagged",
                input_ids=[existing.id, incoming.id], output_ids=[incoming.id],
                reason=f"cross-linked to existing {existing.type}: {existing.content[:60]!r}",
                actor=actor, actor_name=actor_name,
            )
            store._put(existing)
            store._put(incoming)
            return incoming

        raise ValueError(f"unhandled ConflictPolicy: {p}")

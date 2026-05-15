"""DomainProfile and TypeSpec — the schema layer of TypedMemory.

A profile declares which memory types exist for a given domain, how each
behaves on conflict, and what fields are required to consider a memory of
that type well-formed. Profiles can opt into a shared ``core`` set of types
(fact, note, goal, task, event) so domain profiles don't need to redeclare
generic knowledge primitives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..policy import ConflictPolicy, TypePolicy
from ..schema import Memory


@dataclass(frozen=True)
class TypeSpec:
    """A single memory type's contract within a profile."""
    name: str
    description: str = ""
    conflict_policy: ConflictPolicy = ConflictPolicy.KEEP_BOTH
    half_life_days: float | None = None
    summarizable: bool = False
    required_fields: tuple[str, ...] = ()         # e.g. ("source",) → sources must be non-empty
    allowed_tags: tuple[str, ...] | None = None   # None = open; non-None = strict

    def to_policy(self) -> TypePolicy:
        return TypePolicy(
            half_life_days=self.half_life_days,
            summarizable=self.summarizable,
            conflict_policy=self.conflict_policy,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "conflict_policy": self.conflict_policy.value,
            "half_life_days": self.half_life_days,
            "summarizable": self.summarizable,
            "required_fields": list(self.required_fields),
        }
        if self.allowed_tags is not None:
            d["allowed_tags"] = list(self.allowed_tags)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TypeSpec":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            conflict_policy=ConflictPolicy(d.get("conflict_policy", "keep_both")),
            half_life_days=d.get("half_life_days"),
            summarizable=bool(d.get("summarizable", False)),
            required_fields=tuple(d.get("required_fields", ())),
            allowed_tags=(tuple(d["allowed_tags"]) if d.get("allowed_tags") is not None else None),
        )


# Filled in by ``builtins.py``; broken out so ``DomainProfile.all_types``
# does not depend on import order. ``profiles.__init__`` populates this.
_CORE_TYPES: dict[str, TypeSpec] = {}


def _register_core_types(types: dict[str, TypeSpec]) -> None:
    _CORE_TYPES.clear()
    _CORE_TYPES.update(types)


@dataclass
class DomainProfile:
    """Schema for one domain: types + their policies + a prompt template."""

    name: str
    description: str = ""
    types: dict[str, TypeSpec] = field(default_factory=dict)
    include_core_types: bool = False
    prompt_template: str | None = None
    validators: list[Callable[[Memory], list[str]]] = field(default_factory=list)

    # ── factories ─────────────────────────────────────────────────────────
    @classmethod
    def with_core(
        cls,
        name: str,
        types: dict[str, TypeSpec] | Iterable[TypeSpec] = (),
        *,
        description: str = "",
        prompt_template: str | None = None,
    ) -> "DomainProfile":
        """Sugar for a profile that opts into the shared core types."""
        return cls(
            name=name,
            description=description,
            types=_coerce_types(types),
            include_core_types=True,
            prompt_template=prompt_template,
        )

    @classmethod
    def builtin(cls, name: str) -> "DomainProfile":
        from .builtins import BUILTIN_PROFILES
        if name not in BUILTIN_PROFILES:
            raise KeyError(
                f"unknown built-in profile {name!r}; "
                f"available: {sorted(BUILTIN_PROFILES)}"
            )
        return BUILTIN_PROFILES[name]()

    # ── views ─────────────────────────────────────────────────────────────
    def all_types(self) -> dict[str, TypeSpec]:
        """Effective type map. Core types are merged when opted in; profile
        types override on name collision."""
        if not self.include_core_types:
            return dict(self.types)
        merged = dict(_CORE_TYPES)
        merged.update(self.types)
        return merged

    def spec_for(self, type_name: str) -> TypeSpec | None:
        return self.all_types().get(type_name)

    def has_type(self, type_name: str) -> bool:
        return type_name in self.all_types()

    def policies(self) -> dict[str, TypePolicy]:
        return {n: s.to_policy() for n, s in self.all_types().items()}

    # ── validation ────────────────────────────────────────────────────────
    def validate(self, m: Memory) -> list[str]:
        """Return a list of error strings; empty list = valid."""
        errors: list[str] = []

        spec = self.spec_for(m.type)
        if spec is None:
            errors.append(
                f"type {m.type!r} is not declared in profile {self.name!r}; "
                f"available: {sorted(self.all_types())}"
            )
            return errors  # no further checks make sense

        for fld in spec.required_fields:
            if fld == "source":
                if not m.sources:
                    errors.append(f"type {m.type!r} requires at least one source")
            elif fld == "subject":
                if not m.subject:
                    errors.append(f"type {m.type!r} requires a subject")
            elif fld == "tags":
                if not m.tags:
                    errors.append(f"type {m.type!r} requires at least one tag")
            else:
                value = getattr(m, fld, None)
                if value in (None, "", [], (), {}):
                    errors.append(f"type {m.type!r} requires field {fld!r}")

        if spec.allowed_tags is not None:
            disallowed = [t for t in m.tags if t not in spec.allowed_tags]
            if disallowed:
                errors.append(
                    f"type {m.type!r} disallows tags {disallowed}; "
                    f"allowed: {list(spec.allowed_tags)}"
                )

        for v in self.validators:
            errors.extend(v(m))

        return errors

    # ── serialization ─────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "include_core_types": self.include_core_types,
            "types": {n: s.to_dict() for n, s in self.types.items()},
            "prompt_template": self.prompt_template,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DomainProfile":
        raw_types = d.get("types", {})
        # Allow either dict[name, spec] or list[spec-with-name].
        if isinstance(raw_types, list):
            types = {t["name"]: TypeSpec.from_dict(t) for t in raw_types}
        else:
            types = {}
            for n, t in raw_types.items():
                # If the dict-entry omits "name", inject from key.
                entry = dict(t)
                entry.setdefault("name", n)
                types[n] = TypeSpec.from_dict(entry)
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            types=types,
            include_core_types=bool(d.get("include_core_types", False)),
            prompt_template=d.get("prompt_template"),
        )


def _coerce_types(types: dict[str, TypeSpec] | Iterable[TypeSpec]) -> dict[str, TypeSpec]:
    if isinstance(types, dict):
        return dict(types)
    return {s.name: s for s in types}

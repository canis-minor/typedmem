"""Extractors: text → list[Memory].

Two implementations live here:
  RuleBasedExtractor — zero-dep regex extractor (v0.1)
  LLMExtractor       — protocol-driven LLM extractor (v0.3)

Both satisfy the ``Extractor`` Protocol so callers can swap them freely.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, overload

from .llm.base import LLMClient
from .profiles.base import DomainProfile
from .prompts import PROMPTS
from .schema import GoalStatus, Memory, MemoryType
from .source import Source


class Extractor(Protocol):
    def extract(self, text: str, *, subject: str | None = None) -> list[Memory]: ...


def _stamp(memories: list[Memory], workspace: str | None, default_source: Source | None) -> None:
    """Apply workspace and default_source to memories that lack them."""
    for m in memories:
        if workspace is not None:
            m.workspace = workspace
        if default_source is not None and not m.sources:
            m.sources = [default_source]


# Curated cue lists. Designed for the child-development demo first, but broadly
# applicable: each pattern targets a specific memory type with a confidence
# reflecting how unambiguous the cue is.
_PREFERENCE_PATTERNS = [
    (re.compile(r"\b(?:i|user|child)\s+(?:prefer|prefers|like|likes|love|loves)\b", re.I), 0.85),
    (re.compile(r"\b(?:i|user|child)\s+(?:don'?t|do not|doesn'?t|does not)\s+like\b", re.I), 0.85),
    (re.compile(r"\bfavou?rite\b", re.I), 0.75),
]

_GOAL_PATTERNS = [
    (re.compile(r"\b(?:i|we|user)\s+(?:want to|plan to|will|am going to|am trying to)\b", re.I), 0.8),
    (re.compile(r"\b(?:goal|objective|aim)[:\s]", re.I), 0.85),
    (re.compile(r"\blearn(?:ing)? to\b", re.I), 0.7),
]

_FACT_PATTERNS = [
    (re.compile(r"\b(?:is|was|are|were)\s+(?:born|named|aged?)\b", re.I), 0.9),
    (re.compile(r"\bmy name is\b", re.I), 0.95),
    (re.compile(r"\b\d+\s+(?:years?|months?)\s+old\b", re.I), 0.9),
]

_EVENT_PATTERNS = [
    (re.compile(r"\b(?:today|yesterday|this morning|tonight|last night|just now)\b", re.I), 0.8),
    (re.compile(r"\bhappened\b|\bwent to\b|\bvisited\b", re.I), 0.7),
]

# Observation cues — domain-flavored for the child-development demo,
# but tagged so callers can filter.
_OBSERVATION_PATTERNS: list[tuple[re.Pattern[str], float, list[str]]] = [
    (re.compile(r"\bsaid\b|\bword\b|\bspoke\b|\btalked\b", re.I), 0.7, ["language"]),
    (re.compile(r"\b(?:walked|ran|jumped|climbed|tried to wear|grabbed|threw)\b", re.I), 0.7, ["motor"]),
    (re.compile(r"\b(?:cried|laughed|smiled|hugged|got angry|was happy|was sad)\b", re.I), 0.75, ["emotional"]),
    (re.compile(r"\b(?:pointed at|looked at|stared at|noticed)\b", re.I), 0.65, ["cognitive"]),
]


def _split_clauses(text: str) -> list[str]:
    # Split on sentence/clause boundaries while keeping the inner text intact.
    parts = re.split(r"(?<=[.!?])\s+|\s+and\s+|;", text)
    return [p.strip() for p in parts if p and p.strip()]


class RuleBasedExtractor:
    """First-pass extractor. Returns one Memory per matched pattern per clause."""

    def extract(
        self,
        text: str,
        *,
        subject: str | None = None,
        workspace: str | None = None,
        default_source: Source | None = None,
    ) -> list[Memory]:
        memories: list[Memory] = []
        for clause in _split_clauses(text):
            memories.extend(self._extract_clause(clause, subject))
        _stamp(memories, workspace, default_source)
        return memories

    def _extract_clause(self, clause: str, subject: str | None) -> list[Memory]:
        out: list[Memory] = []

        for pattern, conf in _PREFERENCE_PATTERNS:
            if pattern.search(clause):
                out.append(Memory(MemoryType.PREFERENCE, clause, conf, subject=subject))
                break

        for pattern, conf in _GOAL_PATTERNS:
            if pattern.search(clause):
                out.append(Memory(MemoryType.GOAL, clause, conf, subject=subject))
                break

        for pattern, conf in _FACT_PATTERNS:
            if pattern.search(clause):
                out.append(Memory(MemoryType.FACT, clause, conf, subject=subject))
                break

        # Observations can co-fire with events (e.g. "today she said 'more milk'"
        # is both a time-anchored event and a language observation).
        for pattern, conf, tags in _OBSERVATION_PATTERNS:
            if pattern.search(clause):
                out.append(Memory(
                    MemoryType.OBSERVATION, clause, conf,
                    subject=subject, tags=list(tags),
                ))

        for pattern, conf in _EVENT_PATTERNS:
            if pattern.search(clause):
                out.append(Memory(MemoryType.EVENT, clause, conf, subject=subject))
                break

        return out


# ---------------------------------------------------------------------------
# LLM-driven extraction (v0.3)
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    """Full debug view of one ``LLMExtractor.extract`` call.

    Iterable / sized so callers can treat it like a memory list when they
    don't need the diagnostics."""

    raw_response: str
    parsed_json: Any | None
    validation_errors: list[str]
    accepted_memories: list[Memory] = field(default_factory=list)

    def __iter__(self):
        return iter(self.accepted_memories)

    def __len__(self) -> int:
        return len(self.accepted_memories)


_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)
_JSON_ARRAY = re.compile(r"\[\s*(?:\{.*\}\s*,?\s*)*\]", re.DOTALL)


def _strip_to_json(raw: str) -> str:
    """Strip code fences and prose around a JSON array, if present."""
    stripped = _CODE_FENCE.sub("", raw).strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped
    m = _JSON_ARRAY.search(stripped)
    return m.group(0) if m else stripped


def _coerce_tags(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for t in value:
        if isinstance(t, str):
            out.append(t.lower())
        else:
            return None
    return out


def _record_to_memory(
    rec: Any,
    default_subject: str | None,
    default_source: Source | None,
    errors: list[str],
    profile: DomainProfile | None = None,
) -> Memory | None:
    """Validate one raw dict from the LLM. Append to ``errors`` and return
    None when the record is unusable; clamp on recoverable problems."""
    if not isinstance(rec, dict):
        errors.append(f"record is not an object: {rec!r}")
        return None

    raw_type = rec.get("type")
    if not isinstance(raw_type, str) or not raw_type:
        errors.append(f"unknown or missing type: {raw_type!r}")
        return None

    # If a profile is bound, the type must be declared there. Otherwise we
    # fall back to the built-in MemoryType enum for back-compat with v0.3.
    if profile is not None:
        if not profile.has_type(raw_type):
            errors.append(
                f"type {raw_type!r} not declared in profile {profile.name!r}; "
                f"available: {sorted(profile.all_types())}"
            )
            return None
        mtype = raw_type
    else:
        try:
            mtype = MemoryType(raw_type).value
        except (ValueError, TypeError):
            errors.append(f"unknown or missing type: {raw_type!r}")
            return None

    content = rec.get("content")
    if not isinstance(content, str) or not content.strip():
        errors.append(f"missing or empty content for type={mtype}")
        return None

    raw_conf = rec.get("confidence", 0.7)
    try:
        conf = float(raw_conf)
    except (TypeError, ValueError):
        errors.append(f"confidence not a number: {raw_conf!r}; defaulting to 0.7")
        conf = 0.7
    if conf < 0.0 or conf > 1.0:
        errors.append(f"confidence out of range ({conf}); clamping")
        conf = max(0.0, min(1.0, conf))

    tags = _coerce_tags(rec.get("tags"))
    if tags is None:
        errors.append(f"tags must be a list of strings; ignoring for content={content!r}")
        tags = []

    raw_subject = rec.get("subject")
    subject: str | None
    if raw_subject is None or raw_subject == "":
        subject = default_subject
    elif isinstance(raw_subject, str):
        subject = raw_subject
    else:
        errors.append(f"subject must be a string; ignoring for content={content!r}")
        subject = default_subject

    status: str | None = None
    if mtype == MemoryType.GOAL:
        raw_status = rec.get("status")
        if isinstance(raw_status, str):
            try:
                status = GoalStatus(raw_status).value
            except ValueError:
                errors.append(f"unknown goal status: {raw_status!r}; defaulting to active")

    # Source: prefer LLM's "source" field (str | dict), fall back to default.
    sources: list[Source] = []
    raw_source = rec.get("source")
    if raw_source is not None and raw_source != "":
        try:
            lifted = Source.from_any(raw_source)
        except (TypeError, ValueError) as e:
            errors.append(f"invalid source for content={content!r}: {e}")
            lifted = None
        if lifted is not None:
            sources.append(lifted)
    if not sources and default_source is not None:
        sources.append(default_source)

    return Memory(
        type=mtype, content=content.strip(), confidence=conf,
        subject=subject, tags=tags, sources=sources, status=status,
    )


class LLMExtractor:
    """Drive memory extraction through an LLMClient.

    The default install pulls no LLM SDKs; pass an ``LLMClient`` (FakeClient,
    OpenAIClient, AnthropicClient, or your own) at construction.

    Pass ``profile=`` to bind a ``DomainProfile``: the extractor uses its
    prompt template (if set) and validates each extracted record against the
    profile's declared types and ``required_fields``. Records that fail
    validation are dropped and the reason is logged in
    ``ExtractionResult.validation_errors`` — the rest of the batch is kept.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        profile: DomainProfile | None = None,
        domain: str = "general",
        prompt_template: str | None = None,
    ) -> None:
        self.client = client
        self.profile = profile

        if prompt_template is not None:
            self._template = prompt_template
        elif profile is not None and profile.prompt_template:
            self._template = profile.prompt_template
        elif domain in PROMPTS:
            self._template = PROMPTS[domain]
        else:
            # Treat the domain string as a built-in profile name.
            try:
                p = DomainProfile.builtin(domain)
            except KeyError:
                raise ValueError(
                    f"unknown domain {domain!r}; available prompt templates: "
                    f"{sorted(PROMPTS)}. Pass prompt_template=... or profile=..."
                )
            self.profile = self.profile or p
            self._template = p.prompt_template or PROMPTS["general"]

    @overload
    def extract(self, text: str, *, subject: str | None = ..., workspace: str | None = ...,
                default_source: Source | None = ..., return_debug: bool = False) -> list[Memory]: ...
    @overload
    def extract(self, text: str, *, subject: str | None = ..., workspace: str | None = ...,
                default_source: Source | None = ..., return_debug: bool = True) -> ExtractionResult: ...
    def extract(
        self,
        text: str,
        *,
        subject: str | None = None,
        workspace: str | None = None,
        default_source: Source | None = None,
        return_debug: bool = False,
    ):
        prompt = self._template.format(text=text, subject=subject or "")
        raw = self.client.complete(prompt)

        errors: list[str] = []
        parsed: Any | None = None
        memories: list[Memory] = []

        try:
            parsed = json.loads(_strip_to_json(raw))
        except json.JSONDecodeError as e:
            errors.append(f"failed to parse JSON: {e.msg} at pos {e.pos}")

        if parsed is not None:
            if not isinstance(parsed, list):
                errors.append(f"top-level JSON must be an array, got {type(parsed).__name__}")
            else:
                for rec in parsed:
                    m = _record_to_memory(rec, subject, default_source, errors, self.profile)
                    if m is None:
                        continue
                    if workspace is not None:
                        m.workspace = workspace
                    # Profile-level validation (required_fields, allowed_tags,
                    # custom validators). Failures drop the memory and log.
                    if self.profile is not None:
                        profile_errors = self.profile.validate(m)
                        if profile_errors:
                            errors.extend(profile_errors)
                            continue
                    memories.append(m)

        if return_debug:
            return ExtractionResult(
                raw_response=raw,
                parsed_json=parsed,
                validation_errors=errors,
                accepted_memories=memories,
            )
        return memories

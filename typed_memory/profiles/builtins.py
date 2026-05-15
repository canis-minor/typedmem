"""Built-in DomainProfiles.

Each factory returns a fresh ``DomainProfile`` so callers can mutate without
contaminating other consumers. The conflict policies and half-lives are
**provisional** — chosen for sensible defaults, but expected to be tuned
per-deployment. Treat the profile dict as a starting point, not gospel.
"""

from __future__ import annotations

from ..policy import ConflictPolicy
from .base import DomainProfile, TypeSpec, _register_core_types


# ── Core: knowledge primitives any agent benefits from ────────────────────
def _core_types() -> dict[str, TypeSpec]:
    return {
        "fact": TypeSpec(
            name="fact",
            description="A stable claim about the world.",
            conflict_policy=ConflictPolicy.KEEP_BOTH,
            half_life_days=None,
        ),
        "note": TypeSpec(
            name="note",
            description="A free-form annotation the agent has captured.",
            conflict_policy=ConflictPolicy.KEEP_BOTH,
            half_life_days=None,
        ),
        "goal": TypeSpec(
            name="goal",
            description="An active objective; replaced when restated.",
            conflict_policy=ConflictPolicy.REPLACE,
            half_life_days=None,
        ),
        "task": TypeSpec(
            name="task",
            description="A concrete action item; replaced on status update.",
            conflict_policy=ConflictPolicy.REPLACE,
            half_life_days=None,
        ),
        "event": TypeSpec(
            name="event",
            description="A time-anchored occurrence.",
            conflict_policy=ConflictPolicy.KEEP_BOTH,
            half_life_days=14.0,
            summarizable=True,
        ),
    }


def core() -> DomainProfile:
    return DomainProfile(
        name="core",
        description="Generic knowledge primitives: fact, note, goal, task, event.",
        types=_core_types(),
        include_core_types=False,
        prompt_template=_CORE_PROMPT,
    )


# Populate the merge target used by DomainProfile.all_types(). Done at import
# time so ``include_core_types=True`` works for profiles defined below.
_register_core_types(_core_types())


# ── personal: the v0.1–v0.4a default ──────────────────────────────────────
def personal() -> DomainProfile:
    return DomainProfile.with_core(
        name="personal",
        description="Personal-assistant memory: preferences, observations, and core primitives.",
        types={
            "preference": TypeSpec(
                name="preference",
                description="User tendency that can shift over time.",
                conflict_policy=ConflictPolicy.REPLACE,
                half_life_days=60.0,
            ),
            "observation": TypeSpec(
                name="observation",
                description="A low-level signal recorded as it happened.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                half_life_days=7.0,
                summarizable=True,
            ),
        },
        prompt_template=_PERSONAL_PROMPT,
    )


# ── child_development ─────────────────────────────────────────────────────
def child_development() -> DomainProfile:
    return DomainProfile.with_core(
        name="child_development",
        description="Tracking a child's behavior, milestones, and concerns.",
        types={
            "observation": TypeSpec(
                name="observation",
                description="A discrete behavior; tag with the developmental axis.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                half_life_days=7.0,
                summarizable=True,
                allowed_tags=("language", "motor", "emotional", "cognitive", "social"),
            ),
            "milestone": TypeSpec(
                name="milestone",
                description="A developmental milestone (first word, first steps, …).",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                required_fields=("subject",),
            ),
            "concern": TypeSpec(
                name="concern",
                description="Something worth watching or following up on.",
                conflict_policy=ConflictPolicy.FLAG,
                half_life_days=30.0,
            ),
        },
        prompt_template=_CHILD_DEV_PROMPT,
    )


# ── research_paper ────────────────────────────────────────────────────────
def research_paper() -> DomainProfile:
    return DomainProfile.with_core(
        name="research_paper",
        description="Extracting structured knowledge from academic papers.",
        types={
            "claim": TypeSpec(
                name="claim",
                description="An assertion the paper makes.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                required_fields=("source",),
            ),
            "method": TypeSpec(
                name="method",
                description="A technique or procedure used in the work.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                required_fields=("source",),
            ),
            "evidence": TypeSpec(
                name="evidence",
                description="A result, table, or figure that supports a claim.",
                conflict_policy=ConflictPolicy.REINFORCE,
                required_fields=("source",),
            ),
            "limitation": TypeSpec(
                name="limitation",
                description="A constraint, caveat, or threat to validity.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
            ),
            "open_question": TypeSpec(
                name="open_question",
                description="A question the paper raises but does not answer.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
            ),
        },
        prompt_template=_RESEARCH_PROMPT,
    )


# ── engineering_design ────────────────────────────────────────────────────
def engineering_design() -> DomainProfile:
    return DomainProfile.with_core(
        name="engineering_design",
        description="Capturing decisions, constraints, and risks from design docs.",
        types={
            "decision": TypeSpec(
                name="decision",
                description="A choice the team has made.",
                conflict_policy=ConflictPolicy.SUPERSEDE,
                required_fields=("subject",),
            ),
            "constraint": TypeSpec(
                name="constraint",
                description="A bound or rule the system must respect.",
                conflict_policy=ConflictPolicy.REPLACE,
            ),
            "risk": TypeSpec(
                name="risk",
                description="A potential negative outcome to track.",
                conflict_policy=ConflictPolicy.FLAG,
            ),
            "assumption": TypeSpec(
                name="assumption",
                description="A premise the design relies on.",
                conflict_policy=ConflictPolicy.REPLACE,
            ),
            "todo": TypeSpec(
                name="todo",
                description="An engineering action item — synonym for core.task.",
                conflict_policy=ConflictPolicy.REPLACE,
            ),
        },
        prompt_template=_ENGINEERING_PROMPT,
    )


# ── legal ─────────────────────────────────────────────────────────────────
def legal() -> DomainProfile:
    return DomainProfile.with_core(
        name="legal",
        description="Obligations, exceptions, deadlines, and definitions from legal text.",
        types={
            "obligation": TypeSpec(
                name="obligation",
                description="A duty imposed on a party.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                required_fields=("source", "subject"),
            ),
            "exception": TypeSpec(
                name="exception",
                description="A condition under which an obligation does not apply.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                required_fields=("source",),
            ),
            "deadline": TypeSpec(
                name="deadline",
                description="A time-bound requirement.",
                conflict_policy=ConflictPolicy.REPLACE,
            ),
            "definition": TypeSpec(
                name="definition",
                description="A term defined for the purposes of the document.",
                conflict_policy=ConflictPolicy.SUPERSEDE,
            ),
            "citation": TypeSpec(
                name="citation",
                description="A reference to another legal instrument.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
            ),
        },
        prompt_template=_LEGAL_PROMPT,
    )


# ── medical_literature ────────────────────────────────────────────────────
def medical_literature() -> DomainProfile:
    return DomainProfile.with_core(
        name="medical_literature",
        description="Findings, populations, interventions, and outcomes from medical papers.",
        types={
            "finding": TypeSpec(
                name="finding",
                description="A clinically relevant result the paper reports.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
                required_fields=("source",),
            ),
            "population": TypeSpec(
                name="population",
                description="The patient group studied.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
            ),
            "intervention": TypeSpec(
                name="intervention",
                description="The treatment or procedure applied.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
            ),
            "outcome": TypeSpec(
                name="outcome",
                description="A measured endpoint; corroboration across papers reinforces.",
                conflict_policy=ConflictPolicy.REINFORCE,
                required_fields=("source",),
            ),
            "limitation": TypeSpec(
                name="limitation",
                description="A caveat or threat to validity.",
                conflict_policy=ConflictPolicy.KEEP_BOTH,
            ),
        },
        prompt_template=_MEDICAL_PROMPT,
    )


BUILTIN_PROFILES: dict[str, callable] = {
    "core": core,
    "personal": personal,
    "child_development": child_development,
    "research_paper": research_paper,
    "engineering_design": engineering_design,
    "legal": legal,
    "medical_literature": medical_literature,
}


# ── Prompt templates ─────────────────────────────────────────────────────
# Output contract is identical to v0.3 (JSON array, no prose, no fences).
# Each profile injects its own type guide.

_SHARED_OUTPUT_RULES = """\
Output rules (strict):
  - Return ONLY a JSON array. No prose. No markdown. No code fences.
  - If nothing is extractable, return [].
  - Do not invent details not supported by the text.
  - Each item: type, content, confidence in [0,1]; optional subject, tags, source.
"""

_CORE_PROMPT = f"""\
You are a structured memory extractor. Read the input text and produce a JSON
array of memory items.

Available types:
  fact   stable information
  note   free-form annotation
  goal   an active objective
  task   a concrete action item
  event  a time-anchored occurrence

{_SHARED_OUTPUT_RULES}

Subject context (may be empty): {{subject}}

Text:
\"\"\"
{{text}}
\"\"\"

JSON array:"""

_PERSONAL_PROMPT = f"""\
You are a personal-assistant memory extractor. Capture user-relevant items.

Available types:
  fact         stable info about the user
  note         free-form note
  goal         active user objective
  task         action item
  event        time-anchored occurrence
  preference   user tendency that can shift
  observation  low-level signal observed during conversation

{_SHARED_OUTPUT_RULES}

Subject context (may be empty): {{subject}}

Text:
\"\"\"
{{text}}
\"\"\"

JSON array:"""

_CHILD_DEV_PROMPT = f"""\
You are a child-development memory extractor.

Available types:
  fact         stable info (e.g., birthdate)
  note         free-form note
  goal         active goal (e.g., learn to count)
  task         caregiver action item
  event        time-anchored occurrence
  observation  a discrete behavior; tag with one of:
               language | motor | emotional | cognitive | social
  milestone    developmental milestone (first word, first steps, …)
  concern      something worth watching or following up on

A time-anchored sentence typically yields BOTH an event AND one or more
observations.

{_SHARED_OUTPUT_RULES}

Subject context (may be empty): {{subject}}

Text:
\"\"\"
{{text}}
\"\"\"

JSON array:"""

_RESEARCH_PROMPT = f"""\
You are a research-paper memory extractor.

Available types:
  fact            stable background fact
  note            free-form annotation
  goal            stated research aim
  task            follow-up the reader should do
  event           e.g., a result reported in a specific year
  claim           an assertion the paper makes  (requires source)
  method          a technique used in the work   (requires source)
  evidence        a result/figure supporting a claim  (requires source)
  limitation      a caveat or threat to validity
  open_question   a question the paper raises but does not answer

Every claim / method / evidence MUST include a source object with at least
``document_id`` (and ideally ``chunk_id`` and ``span``).

{_SHARED_OUTPUT_RULES}

Subject context (may be empty): {{subject}}

Text:
\"\"\"
{{text}}
\"\"\"

JSON array:"""

_ENGINEERING_PROMPT = f"""\
You are an engineering-design memory extractor.

Available types:
  fact         stable technical fact
  note         free-form annotation
  goal         project objective
  task         engineering action item
  event        a time-anchored occurrence
  decision     a choice the team has made (requires subject; SUPERSEDES old)
  constraint   a bound or rule the system must respect
  risk         a potential negative outcome to track (FLAGS on conflict)
  assumption   a premise the design relies on
  todo         synonym for task in engineering contexts

{_SHARED_OUTPUT_RULES}

Subject context (may be empty): {{subject}}

Text:
\"\"\"
{{text}}
\"\"\"

JSON array:"""

_LEGAL_PROMPT = f"""\
You are a legal-document memory extractor.

Available types:
  fact         stable legal fact
  note         free-form annotation
  goal         legal objective
  task         legal action item
  event        a time-anchored legal occurrence
  obligation   a duty on a party (requires source and subject)
  exception    a carve-out from an obligation (requires source)
  deadline     a time-bound requirement
  definition   a term defined in the document (SUPERSEDES prior definitions)
  citation     a reference to another instrument

{_SHARED_OUTPUT_RULES}

Subject context (may be empty): {{subject}}

Text:
\"\"\"
{{text}}
\"\"\"

JSON array:"""

_MEDICAL_PROMPT = f"""\
You are a medical-literature memory extractor.

Available types:
  fact          stable medical fact
  note          free-form annotation
  goal          research aim
  task          follow-up action
  event         a time-anchored occurrence
  finding       a clinically relevant result (requires source)
  population    the patient group studied
  intervention  the treatment or procedure
  outcome       a measured endpoint (REINFORCES on corroboration; requires source)
  limitation    a caveat or threat to validity

{_SHARED_OUTPUT_RULES}

Subject context (may be empty): {{subject}}

Text:
\"\"\"
{{text}}
\"\"\"

JSON array:"""

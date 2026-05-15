"""Prompt templates for LLMExtractor.

Templates use two placeholders: ``{text}`` (always required) and ``{subject}``
(may be empty). Output contract is the same across templates: a JSON array of
memory objects, nothing else — no prose, no code fences.
"""

from __future__ import annotations

GENERAL = """\
You are a structured memory extractor. Read the input text and produce a JSON \
array of memory items the system should remember.

Each item is an object with these fields:
  type:       one of "fact" | "preference" | "goal" | "event" | "observation"
  content:    short string (one short sentence) capturing the memory
  confidence: float in [0, 1] for how strongly the text supports this memory
  subject:    (optional) who/what the memory is about
  tags:       (optional) list of short topical tags, lowercase

Type guide:
  fact         stable information (birthdate, name, location)
  preference   tendencies that can change (likes/dislikes, habits)
  goal         an active objective ("learn to count")
  event        a time-anchored occurrence ("went to park today")
  observation  a low-level signal often paired with an event \
("said 'milk'", "tried to wear shoes")

Output rules (strict):
  - Return ONLY a JSON array. No prose. No markdown. No code fences.
  - If nothing is extractable, return [].
  - Do not invent details not supported by the text.
  - Prefer multiple small items over one large one.

Subject context (may be empty): {subject}

Text:
\"\"\"
{text}
\"\"\"

JSON array:"""


CHILD_DEVELOPMENT = """\
You are a child-development memory extractor. Read the text and produce a JSON \
array of memory items about the child's behavior, milestones, and preferences.

Each item is an object with these fields:
  type:       one of "fact" | "preference" | "goal" | "event" | "observation"
  content:    short string (one short sentence) capturing the memory
  confidence: float in [0, 1]
  subject:    (optional) who/what the memory is about — usually "child"
  tags:       (optional) list of short topical tags

For observations, prefer one of these tags when applicable:
  language    speech, words, vocalizations
  motor       walking, climbing, grasping, dressing
  emotional   crying, laughing, hugging, mood shifts
  cognitive   pointing, recognizing, problem-solving, attention
  social      interaction with people/pets

Common pattern: a time-anchored sentence yields BOTH an event (anchoring \
when it happened) AND one or more observations (what the child did).

Output rules (strict):
  - Return ONLY a JSON array. No prose. No markdown. No code fences.
  - If nothing is extractable, return [].
  - Do not invent details not supported by the text.

Subject context (may be empty): {subject}

Text:
\"\"\"
{text}
\"\"\"

JSON array:"""


PROMPTS: dict[str, str] = {
    "general": GENERAL,
    "child_development": CHILD_DEVELOPMENT,
}

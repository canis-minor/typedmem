"""Before vs after: an agent that learns user preferences over time.

Two runs of the same code:

  WITHOUT TypedMemory:
      Each "session" is independent. The agent has no idea the user
      changed their mind. Contradictions are silent.

  WITH TypedMemory:
      mem.remember() captures each session's signal.
      mem.recall() lets the next session see the current state.
      mem.reflect() surfaces drift / contradictions for debugging.

Run this file to see both side by side.
"""

from typedmem import AgentMemory


def section(title: str) -> None:
    print(f"\n══ {title} " + "═" * max(0, 60 - len(title)))


# ── Pretend these are the user's turns across multiple sessions ───────────────
SESSION_SIGNALS = [
    ("monday",    "User likes concise answers"),
    ("tuesday",   "User prefers more detailed responses"),
    ("wednesday", "User likes concise answers actually"),
    ("thursday",  "User prefers detailed answers — sorry, changed my mind"),
    ("friday",    "User likes terse answers please"),
]


# ── 1. WITHOUT TypedMemory ───────────────────────────────────────────────────
section("Without TypedMemory (the silent-contradiction problem)")
print("Each session is independent. Whatever the user said last is what")
print("the agent stores — but it can't see the pattern of constant flipping.\n")

current_state = None
for day, utterance in SESSION_SIGNALS:
    current_state = utterance       # naive: just overwrite
    print(f"  [{day:<9}] heard: {utterance!r}")
    print(f"             agent now thinks: {current_state!r}")

print("\n→ The user flipped 5 times. The agent has no record of any of it.")
print("→ Tomorrow the agent contradicts itself; nobody can debug why.")


# ── 2. WITH TypedMemory ──────────────────────────────────────────────────────
section("With TypedMemory")
mem = AgentMemory(profile="personal", workspace="alice")

for day, utterance in SESSION_SIGNALS:
    added = mem.remember(utterance, subject="user")
    types = [m.type for m in added]
    print(f"  [{day:<9}] remembered: {utterance!r}  → typed as {types}")

section("What the agent recalls today")
for hit in mem.recall("what kind of answers does the user want?", limit=3):
    print(f"  score={hit.score:.2f}  [{hit.memory.type}] {hit.memory.content}")

section("What reflection reveals")
report = mem.reflect(drift_min_replaces=2)
print(f"  {report.summary()}")
if report.drift_records:
    for r in report.drift_records:
        print(f"  → {r.reason}")

section("Bottom line")
print("Both runs saw the same 5 utterances. Only the second run can answer:")
print("  • What does the user prefer right now?  → recall()")
print("  • Are they flipping a lot?              → reflect() catches drift")
print("  • What did they say on Tuesday?         → store has the full log")
print()
print("This is what 'persistent, evolving, context-aware memory' actually")
print("buys an agent: the ability to debug its own behavior over time.")

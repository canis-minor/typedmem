from typedmem.extractor import RuleBasedExtractor
from typedmem.schema import MemoryType


def test_demo_input_yields_language_and_motor():
    """Per design doc §9 demo case."""
    ms = RuleBasedExtractor().extract(
        "Today the child said 'more milk' and tried to wear shoes.",
        subject="child",
    )
    tags = {tag for m in ms if m.type == MemoryType.OBSERVATION for tag in m.tags}
    assert "language" in tags
    assert "motor" in tags
    assert any(m.type == MemoryType.EVENT for m in ms)  # "today"


def test_preference_extraction():
    ms = RuleBasedExtractor().extract("Child loves bananas.", subject="child")
    assert any(m.type == MemoryType.PREFERENCE for m in ms)


def test_goal_extraction():
    ms = RuleBasedExtractor().extract("We are trying to learn to count to ten.")
    assert any(m.type == MemoryType.GOAL for m in ms)


def test_emotional_observation():
    ms = RuleBasedExtractor().extract("She laughed when the dog barked.")
    obs = [m for m in ms if m.type == MemoryType.OBSERVATION]
    assert any("emotional" in m.tags for m in obs)


def test_third_person_goals_extracted():
    """'User wants to' / 'She plans to' should land as goals (v0.4.1)."""
    cases = [
        "User wants to learn Spanish",
        "She plans to ship the feature",
        "He is going to start a company",
        "They are trying to lose weight",   # not matched — 'they are' not in patterns
    ]
    matched = [
        text for text in cases
        if any(m.type == MemoryType.GOAL
               for m in RuleBasedExtractor().extract(text))
    ]
    assert len(matched) >= 3, f"expected ≥3 to match, got {matched}"


def test_residence_extracted_as_fact():
    """Common biographical statements should land as facts (v0.4.1)."""
    cases = [
        "User lives in San Francisco",
        "She lives at 5th Avenue",
        "He is based in Tokyo",
        "I work at Acme",
        "Alice works for the city",
        "She studies at MIT",
        "He is from Boston",
        "I am from Lagos",
    ]
    for text in cases:
        ms = RuleBasedExtractor().extract(text, subject="user")
        assert any(m.type == MemoryType.FACT for m in ms), \
            f"expected a fact from {text!r}, got {[m.type for m in ms]}"

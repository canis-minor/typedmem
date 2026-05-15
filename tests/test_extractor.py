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

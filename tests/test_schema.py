import pytest

from typedmem.schema import GoalStatus, Memory, MemoryType


def test_memory_defaults():
    m = Memory(MemoryType.FACT, "the sky is blue")
    assert m.id
    assert m.confidence == 1.0
    assert m.status is None


def test_goal_defaults_active():
    m = Memory(MemoryType.GOAL, "learn to count")
    assert m.status == GoalStatus.ACTIVE


def test_invalid_confidence():
    with pytest.raises(ValueError):
        Memory(MemoryType.FACT, "x", confidence=1.5)


def test_to_dict_serializes_enums_and_times():
    m = Memory(MemoryType.PREFERENCE, "likes tea")
    d = m.to_dict()
    assert d["type"] == "preference"
    assert isinstance(d["timestamp"], str)


def test_accepts_string_type():
    m = Memory("event", "went to the park")  # type: ignore[arg-type]
    assert m.type == MemoryType.EVENT

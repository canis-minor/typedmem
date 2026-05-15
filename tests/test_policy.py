from datetime import timedelta

from typedmem.policy import PolicyEngine
from typedmem.schema import Memory, MemoryType, _now


def test_fact_does_not_decay():
    policy = PolicyEngine()
    old = Memory(MemoryType.FACT, "born 2024", timestamp=_now() - timedelta(days=365))
    assert policy.effective_confidence(old) == old.confidence


def test_observation_decays():
    policy = PolicyEngine()
    old = Memory(MemoryType.OBSERVATION, "said hi", timestamp=_now() - timedelta(days=7))
    # half-life is 7 days → ~0.5 of original confidence
    assert 0.4 < policy.effective_confidence(old) < 0.6


def test_preference_replacement():
    policy = PolicyEngine()
    old = Memory(MemoryType.PREFERENCE, "likes tea", confidence=0.8,
                 timestamp=_now() - timedelta(days=10), subject="user")
    new = Memory(MemoryType.PREFERENCE, "likes coffee", confidence=0.9, subject="user")
    assert policy.should_replace(old, new) is True


def test_fact_not_replaceable():
    policy = PolicyEngine()
    old = Memory(MemoryType.FACT, "born 2024", subject="child")
    new = Memory(MemoryType.FACT, "born 2025", subject="child")
    assert policy.should_replace(old, new) is False

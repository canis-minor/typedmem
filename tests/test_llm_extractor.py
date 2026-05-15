"""LLMExtractor tests — FakeClient only, no live API calls."""

import json

import pytest

from typed_memory import (
    ExtractionResult,
    FakeClient,
    GoalStatus,
    LLMExtractor,
    Memory,
    MemoryType,
)


def _resp(items):
    return json.dumps(items)


def test_valid_json_yields_memories():
    raw = _resp([
        {"type": "preference", "content": "loves bananas", "confidence": 0.9,
         "subject": "child", "tags": ["food"]},
        {"type": "goal", "content": "learn to count", "confidence": 0.8},
    ])
    ex = LLMExtractor(FakeClient(raw))
    ms = ex.extract("…")
    assert len(ms) == 2
    assert {m.type for m in ms} == {MemoryType.PREFERENCE, MemoryType.GOAL}
    pref = next(m for m in ms if m.type == MemoryType.PREFERENCE)
    assert pref.subject == "child" and pref.tags == ["food"]


def test_strips_markdown_code_fences():
    raw = '```json\n[{"type": "fact", "content": "born 2024", "confidence": 0.95}]\n```'
    ms = LLMExtractor(FakeClient(raw)).extract("…")
    assert len(ms) == 1 and ms[0].type == MemoryType.FACT


def test_extracts_array_when_wrapped_in_prose():
    raw = 'Here you go: [{"type": "event", "content": "went to park", "confidence": 0.7}] hope this helps'
    ms = LLMExtractor(FakeClient(raw)).extract("…")
    assert len(ms) == 1 and ms[0].type == MemoryType.EVENT


def test_malformed_json_returns_empty_and_records_error():
    ex = LLMExtractor(FakeClient("not json at all {"))
    debug = ex.extract("…", return_debug=True)
    assert isinstance(debug, ExtractionResult)
    assert debug.accepted_memories == []
    assert any("parse" in e.lower() for e in debug.validation_errors)


def test_top_level_not_array_records_error():
    raw = json.dumps({"type": "fact", "content": "x", "confidence": 0.9})
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    assert debug.accepted_memories == []
    assert any("array" in e.lower() for e in debug.validation_errors)


def test_unknown_type_skipped():
    raw = _resp([
        {"type": "unicorn", "content": "x", "confidence": 0.9},
        {"type": "fact", "content": "kept", "confidence": 0.9},
    ])
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    assert [m.content for m in debug.accepted_memories] == ["kept"]
    assert any("unicorn" in e for e in debug.validation_errors)


def test_missing_content_skipped():
    raw = _resp([
        {"type": "fact", "confidence": 0.9},
        {"type": "fact", "content": "", "confidence": 0.9},
        {"type": "fact", "content": "ok", "confidence": 0.9},
    ])
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    assert [m.content for m in debug.accepted_memories] == ["ok"]
    assert sum(1 for e in debug.validation_errors if "content" in e) == 2


def test_confidence_clamped_high_and_low():
    raw = _resp([
        {"type": "fact", "content": "high", "confidence": 1.7},
        {"type": "fact", "content": "low", "confidence": -0.2},
    ])
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    conf_by_content = {m.content: m.confidence for m in debug.accepted_memories}
    assert conf_by_content == {"high": 1.0, "low": 0.0}
    assert sum(1 for e in debug.validation_errors if "clamp" in e) == 2


def test_confidence_default_when_missing():
    raw = _resp([{"type": "fact", "content": "x"}])
    ms = LLMExtractor(FakeClient(raw)).extract("…")
    assert ms[0].confidence == 0.7


def test_confidence_non_numeric_defaults():
    raw = _resp([{"type": "fact", "content": "x", "confidence": "very high"}])
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    assert debug.accepted_memories[0].confidence == 0.7
    assert any("confidence not a number" in e for e in debug.validation_errors)


def test_non_object_records_skipped():
    raw = _resp(["just a string", 42, {"type": "fact", "content": "kept", "confidence": 0.9}])
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    assert [m.content for m in debug.accepted_memories] == ["kept"]
    assert sum(1 for e in debug.validation_errors if "not an object" in e) == 2


def test_invalid_tags_ignored_not_skipped():
    raw = _resp([{"type": "fact", "content": "x", "confidence": 0.9, "tags": "not a list"}])
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    assert len(debug.accepted_memories) == 1
    assert debug.accepted_memories[0].tags == []
    assert any("tags" in e for e in debug.validation_errors)


def test_subject_falls_back_to_default():
    raw = _resp([{"type": "observation", "content": "smiled", "confidence": 0.8}])
    ms = LLMExtractor(FakeClient(raw)).extract("…", subject="child")
    assert ms[0].subject == "child"


def test_record_subject_wins_over_default():
    raw = _resp([{"type": "fact", "content": "x", "confidence": 0.9, "subject": "alice"}])
    ms = LLMExtractor(FakeClient(raw)).extract("…", subject="bob")
    assert ms[0].subject == "alice"


def test_goal_status_parsed():
    raw = _resp([{"type": "goal", "content": "ship v0.3", "confidence": 0.9, "status": "resolved"}])
    ms = LLMExtractor(FakeClient(raw)).extract("…")
    assert ms[0].status == GoalStatus.RESOLVED


def test_goal_default_status_active():
    raw = _resp([{"type": "goal", "content": "ship", "confidence": 0.9}])
    ms = LLMExtractor(FakeClient(raw)).extract("…")
    assert ms[0].status == GoalStatus.ACTIVE


def test_empty_array_is_clean():
    debug = LLMExtractor(FakeClient("[]")).extract("…", return_debug=True)
    assert debug.accepted_memories == []
    assert debug.validation_errors == []


def test_unknown_domain_raises():
    with pytest.raises(ValueError, match="unknown domain"):
        LLMExtractor(FakeClient("[]"), domain="quantum_physics")


def test_child_development_domain_uses_dedicated_prompt():
    fake = FakeClient("[]")
    LLMExtractor(fake, domain="child_development").extract("any text")
    prompt = fake.calls[0]
    assert "child-development" in prompt.lower() or "child development" in prompt.lower()


def test_custom_prompt_template():
    fake = FakeClient("[]")
    ex = LLMExtractor(fake, prompt_template="custom: {text}")
    ex.extract("hello")
    assert fake.calls[0] == "custom: hello"


def test_return_debug_shape():
    raw = _resp([{"type": "fact", "content": "x", "confidence": 0.9}])
    debug = LLMExtractor(FakeClient(raw)).extract("…", return_debug=True)
    assert isinstance(debug, ExtractionResult)
    assert debug.raw_response == raw
    assert debug.parsed_json == [{"type": "fact", "content": "x", "confidence": 0.9}]
    assert len(debug) == 1  # __len__
    assert list(debug)[0].content == "x"  # __iter__


def test_satisfies_extractor_protocol_when_used_normally():
    """Default extract() must return list[Memory] so it slots into the protocol."""
    raw = _resp([{"type": "fact", "content": "x", "confidence": 0.9}])
    result = LLMExtractor(FakeClient(raw)).extract("…")
    assert isinstance(result, list)
    assert all(isinstance(m, Memory) for m in result)

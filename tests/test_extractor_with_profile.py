"""LLMExtractor bound to a DomainProfile."""

import json

import pytest

from typed_memory import (
    DomainProfile,
    FakeClient,
    LLMExtractor,
    Source,
)


def _resp(items):
    return json.dumps(items)


def test_profile_uses_its_prompt_template():
    """Bound profile's prompt template is used over the default."""
    profile = DomainProfile.builtin("research_paper")
    fake = FakeClient("[]")
    LLMExtractor(fake, profile=profile).extract("Some paper text.")
    sent = fake.calls[0]
    assert "research-paper" in sent.lower() or "research paper" in sent.lower()
    assert "claim" in sent
    assert "evidence" in sent


def test_profile_accepts_declared_types():
    profile = DomainProfile.builtin("research_paper")
    raw = _resp([
        {"type": "claim", "content": "X improves Y", "confidence": 0.9,
         "source": {"document_id": "paper1.pdf"}},
    ])
    ms = LLMExtractor(FakeClient(raw), profile=profile).extract("…")
    assert len(ms) == 1
    assert ms[0].type == "claim"
    assert ms[0].sources[0].document_id == "paper1.pdf"


def test_profile_rejects_undeclared_type():
    profile = DomainProfile.builtin("research_paper")
    raw = _resp([
        {"type": "preference", "content": "I like this paper", "confidence": 0.9},
        {"type": "claim", "content": "kept", "confidence": 0.9,
         "source": {"document_id": "p.pdf"}},
    ])
    debug = LLMExtractor(FakeClient(raw), profile=profile).extract("…", return_debug=True)
    assert [m.content for m in debug.accepted_memories] == ["kept"]
    assert any("preference" in e for e in debug.validation_errors)


def test_profile_required_fields_enforced():
    """A claim without a source must be dropped, with an error logged."""
    profile = DomainProfile.builtin("research_paper")
    raw = _resp([
        {"type": "claim", "content": "no source provided", "confidence": 0.9},
    ])
    debug = LLMExtractor(FakeClient(raw), profile=profile).extract("…", return_debug=True)
    assert debug.accepted_memories == []
    assert any("source" in e for e in debug.validation_errors)


def test_profile_required_fields_satisfied_by_default_source():
    """default_source kwarg should satisfy required_fields=source."""
    profile = DomainProfile.builtin("research_paper")
    raw = _resp([{"type": "claim", "content": "x", "confidence": 0.9}])
    src = Source(document_id="paper.pdf")
    ms = LLMExtractor(FakeClient(raw), profile=profile).extract("…", default_source=src)
    assert len(ms) == 1
    assert ms[0].sources[0].document_id == "paper.pdf"


def test_profile_allowed_tags_enforced():
    """child_development restricts observation tags."""
    profile = DomainProfile.builtin("child_development")
    raw = _resp([
        {"type": "observation", "content": "x", "confidence": 0.9,
         "tags": ["language", "made_up"]},
    ])
    debug = LLMExtractor(FakeClient(raw), profile=profile).extract("…", return_debug=True)
    assert debug.accepted_memories == []
    assert any("made_up" in str(e) for e in debug.validation_errors)


def test_back_compat_domain_arg_still_works():
    """v0.3-style domain= without profile= keeps working."""
    fake = FakeClient("[]")
    LLMExtractor(fake, domain="general").extract("x")
    assert "JSON array" in fake.calls[0]


def test_unknown_domain_falls_through_to_builtin_profile():
    """Unknown ``domain`` name resolves to the matching built-in profile."""
    fake = FakeClient("[]")
    ex = LLMExtractor(fake, domain="legal")
    assert ex.profile is not None
    assert ex.profile.name == "legal"


def test_unknown_domain_raises_when_no_profile_match():
    with pytest.raises(ValueError, match="unknown domain"):
        LLMExtractor(FakeClient("[]"), domain="quantum_physics_v2")

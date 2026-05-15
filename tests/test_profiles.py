"""DomainProfile and TypeSpec — core merging, validation, policy bridge."""

import pytest

from typedmem import (
    ConflictPolicy,
    DomainProfile,
    Memory,
    PolicyEngine,
    Source,
    TypeSpec,
)
from typedmem.profiles.builtins import BUILTIN_PROFILES


# ── TypeSpec ─────────────────────────────────────────────────────────────────
def test_typespec_to_policy_round_trip():
    spec = TypeSpec(name="evidence", conflict_policy=ConflictPolicy.REINFORCE, half_life_days=30.0)
    pol = spec.to_policy()
    assert pol.conflict_policy is ConflictPolicy.REINFORCE
    assert pol.half_life_days == 30.0


# ── Core merge ───────────────────────────────────────────────────────────────
def test_no_core_when_flag_unset():
    p = DomainProfile(name="x", types={"claim": TypeSpec(name="claim")})
    assert p.has_type("claim")
    assert not p.has_type("fact")


def test_core_merged_when_flag_set():
    p = DomainProfile.with_core(name="x", types={"claim": TypeSpec(name="claim")})
    assert p.has_type("claim")
    assert p.has_type("fact")    # from core
    assert p.has_type("note")
    assert p.has_type("event")


def test_profile_overrides_core_type():
    p = DomainProfile.with_core(
        name="strict",
        types={"fact": TypeSpec(name="fact", conflict_policy=ConflictPolicy.FLAG)},
    )
    assert p.spec_for("fact").conflict_policy is ConflictPolicy.FLAG


# ── Built-in profiles ────────────────────────────────────────────────────────
def test_all_seven_builtins_load():
    assert set(BUILTIN_PROFILES) == {
        "core", "personal", "child_development",
        "research_paper", "engineering_design", "legal", "medical_literature",
    }
    for name in BUILTIN_PROFILES:
        p = DomainProfile.builtin(name)
        assert p.types or name == "core"   # core has its own types, others may rely on merge
        assert p.all_types()
        assert p.prompt_template


def test_personal_matches_v04a_defaults():
    p = DomainProfile.builtin("personal")
    pols = p.policies()
    assert pols["fact"].conflict_policy is ConflictPolicy.KEEP_BOTH
    assert pols["preference"].conflict_policy is ConflictPolicy.REPLACE
    assert pols["preference"].half_life_days == 60.0
    assert pols["observation"].half_life_days == 7.0


def test_research_paper_conflict_policies():
    p = DomainProfile.builtin("research_paper")
    pols = p.policies()
    assert pols["claim"].conflict_policy is ConflictPolicy.KEEP_BOTH
    assert pols["evidence"].conflict_policy is ConflictPolicy.REINFORCE
    assert "fact" in pols  # core types merged


def test_engineering_decision_supersedes():
    p = DomainProfile.builtin("engineering_design")
    assert p.spec_for("decision").conflict_policy is ConflictPolicy.SUPERSEDE
    assert p.spec_for("risk").conflict_policy is ConflictPolicy.FLAG


def test_legal_definition_supersedes():
    p = DomainProfile.builtin("legal")
    assert p.spec_for("definition").conflict_policy is ConflictPolicy.SUPERSEDE


# ── Validation ───────────────────────────────────────────────────────────────
def test_unknown_type_errors():
    p = DomainProfile.builtin("research_paper")
    m = Memory(type="unicorn", content="x")
    errs = p.validate(m)
    assert errs and "unicorn" in errs[0]


def test_required_source_missing():
    p = DomainProfile.builtin("research_paper")
    m = Memory(type="claim", content="x")
    errs = p.validate(m)
    assert any("source" in e for e in errs)


def test_required_source_present_passes():
    p = DomainProfile.builtin("research_paper")
    m = Memory(type="claim", content="x", sources=[Source(document_id="paper.pdf")])
    errs = p.validate(m)
    assert errs == []


def test_required_subject_missing():
    p = DomainProfile.builtin("engineering_design")
    m = Memory(type="decision", content="ship v0.4")
    errs = p.validate(m)
    assert any("subject" in e for e in errs)


def test_disallowed_tag_flagged():
    p = DomainProfile.builtin("child_development")
    m = Memory(type="observation", content="x", tags=["language", "made_up_axis"])
    errs = p.validate(m)
    assert any("made_up_axis" in str(e) for e in errs)


def test_allowed_tags_pass():
    p = DomainProfile.builtin("child_development")
    m = Memory(type="observation", content="x", tags=["language", "motor"])
    errs = p.validate(m)
    assert errs == []


# ── PolicyEngine bridge ──────────────────────────────────────────────────────
def test_policyengine_from_profile():
    p = DomainProfile.builtin("research_paper")
    engine = PolicyEngine.from_profile(p)
    assert engine.policy_for("claim").conflict_policy is ConflictPolicy.KEEP_BOTH
    assert engine.policy_for("evidence").conflict_policy is ConflictPolicy.REINFORCE


def test_policyengine_unknown_type_raises():
    engine = PolicyEngine()
    with pytest.raises(KeyError, match="quantum_state"):
        engine.policy_for("quantum_state")


def test_policyengine_default_fallback():
    from typedmem.policy import TypePolicy
    default = TypePolicy(None, False, ConflictPolicy.KEEP_BOTH)
    engine = PolicyEngine(default=default)
    assert engine.policy_for("anything") is default


# ── from_dict / serialization ────────────────────────────────────────────────
def test_round_trip_to_dict_from_dict():
    p = DomainProfile.builtin("legal")
    d = p.to_dict()
    p2 = DomainProfile.from_dict(d)
    assert p2.name == p.name
    assert p2.include_core_types == p.include_core_types
    assert set(p2.types) == set(p.types)
    assert p2.spec_for("definition").conflict_policy is ConflictPolicy.SUPERSEDE


def test_from_dict_types_as_list():
    """YAML/JSON files often express types as a list with name inside each."""
    p = DomainProfile.from_dict({
        "name": "mini",
        "types": [
            {"name": "claim", "conflict_policy": "keep_both"},
            {"name": "evidence", "conflict_policy": "reinforce", "required_fields": ["source"]},
        ],
        "include_core_types": True,
    })
    assert p.has_type("claim") and p.has_type("evidence")
    assert p.spec_for("evidence").required_fields == ("source",)

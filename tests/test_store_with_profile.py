"""Store bound to a profile: validates writes; for_profile classmethod."""

from pathlib import Path

import pytest

from typedmem import (
    ConflictPolicy,
    DomainProfile,
    Memory,
    PolicyEngine,
    SQLiteMemoryStore,
    Source,
)


def test_for_profile_uses_profile_policies(tmp_path: Path):
    profile = DomainProfile.builtin("research_paper")
    with SQLiteMemoryStore.for_profile(profile, path=tmp_path / "m.db") as s:
        a = s.add(Memory(
            type="evidence", content="result A", subject="claim1",
            confidence=0.6, sources=[Source(document_id="paper1.pdf")],
        ))
        s.add(Memory(
            type="evidence", content="result A (corroborated)", subject="claim1",
            confidence=0.8, sources=[Source(document_id="paper2.pdf")],
        ))
        # REINFORCE: single record, two sources, confidence bumped
        items = s.by_type("evidence")
        assert len(items) == 1
        assert {src.document_id for src in items[0].sources} == {"paper1.pdf", "paper2.pdf"}
        assert items[0].confidence > 0.6


def test_engineering_decision_supersedes(tmp_path: Path):
    profile = DomainProfile.builtin("engineering_design")
    with SQLiteMemoryStore.for_profile(profile, path=tmp_path / "m.db") as s:
        old = s.add(Memory(type="decision", content="use postgres", subject="db"))
        new = s.add(Memory(type="decision", content="use sqlite", subject="db"))
        assert s.get(old.id).superseded_by == new.id
        active = s.by_type("decision")
        assert len(active) == 1 and active[0].id == new.id


def test_profile_validation_at_store_raises(tmp_path: Path):
    """Profile-bound stores reject undeclared types at add() time."""
    profile = DomainProfile.builtin("research_paper")
    with SQLiteMemoryStore.for_profile(profile, path=tmp_path / "m.db") as s:
        with pytest.raises(ValueError, match="rejected"):
            s.add(Memory(type="preference", content="x"))


def test_profile_validation_required_fields(tmp_path: Path):
    profile = DomainProfile.builtin("research_paper")
    with SQLiteMemoryStore.for_profile(profile, path=tmp_path / "m.db") as s:
        with pytest.raises(ValueError, match="source"):
            s.add(Memory(type="claim", content="no source provided"))


def test_store_without_profile_accepts_any_type(tmp_path: Path):
    """Default stores are lenient — type strings are not validated."""
    with SQLiteMemoryStore(tmp_path / "m.db") as s:
        s.add(Memory(type="anything", content="x"))
        assert len(s.by_type("anything")) == 1

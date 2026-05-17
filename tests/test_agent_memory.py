"""AgentMemory contract tests."""

from pathlib import Path

import pytest

from typedmem import (
    AgentMemory,
    AgentMemoryReflection,
    DomainProfile,
    FakeClient,
    HashingEmbeddingProvider,
    InMemoryStore,
    LLMExtractor,
    Memory,
)


# ── Construction ─────────────────────────────────────────────────────────────
def test_default_construction_is_in_memory():
    mem = AgentMemory()
    assert len(mem) == 0
    assert mem.profile is not None
    assert mem.profile.name == "personal"


def test_explicit_profile_name():
    mem = AgentMemory(profile="research_paper")
    assert mem.profile.name == "research_paper"


def test_profile_none_disables_binding():
    mem = AgentMemory(profile=None)
    assert mem.profile is None


def test_sqlite_persistence(tmp_path: Path):
    path = tmp_path / "agent.db"
    with AgentMemory(profile=None, path=path) as m1:
        m1.remember("I like jazz")
    with AgentMemory(profile=None, path=path) as m2:
        assert len(m2) == 1


def test_bring_your_own_store():
    store = InMemoryStore()
    mem = AgentMemory(store=store)
    assert mem.store is store


# ── remember ─────────────────────────────────────────────────────────────────
def test_remember_returns_added_memories():
    mem = AgentMemory()
    added = mem.remember("I like jazz")
    assert len(added) == 1
    assert added[0].type == "preference"


def test_remember_extracts_multiple_types_from_one_text():
    mem = AgentMemory()
    added = mem.remember(
        "Today the child said 'more milk' and tried to wear shoes",
        subject="child",
    )
    # Rule extractor surfaces multiple memories from one sentence
    types = {m.type for m in added}
    assert "observation" in types or "event" in types


def test_remember_respects_workspace():
    mem_a = AgentMemory(workspace="alice")
    mem_b = AgentMemory(workspace="bob", store=mem_a.store)
    mem_a.remember("User likes jazz", subject="user")
    mem_b.remember("User likes rock", subject="user")
    # Same store, different workspaces → no slot collision
    assert len(mem_a) == 1
    assert len(mem_b) == 1


# ── recall ───────────────────────────────────────────────────────────────────
def test_recall_returns_relevant_memories():
    mem = AgentMemory()
    mem.remember("I like jazz")
    mem.remember("I live in Tokyo")
    mem.remember("I want to learn Rust")

    hits = mem.recall("what does the user like?")
    assert hits
    contents = [h.memory.content for h in hits]
    # Jazz preference should rank highly for this query
    assert any("jazz" in c.lower() for c in contents)


def test_recall_filters_by_type():
    mem = AgentMemory()
    mem.remember("I like jazz")
    mem.remember("I want to learn Rust")

    hits = mem.recall("learn", types=["goal"])
    assert all(h.memory.type == "goal" for h in hits)


def test_recall_returns_empty_for_empty_store():
    mem = AgentMemory()
    assert mem.recall("anything") == []


# ── reflect ──────────────────────────────────────────────────────────────────
def test_reflect_returns_structured_report():
    mem = AgentMemory()
    mem.remember("User likes jazz", subject="user")
    mem.remember("User likes rock", subject="user")  # REPLACE
    mem.remember("User likes metal", subject="user")  # REPLACE
    mem.remember("User likes punk", subject="user")  # REPLACE

    report = mem.reflect(drift_min_replaces=2)
    assert isinstance(report, AgentMemoryReflection)
    assert report.drift_records  # 3 replaces triggers drift


def test_reflect_summary_when_clean():
    mem = AgentMemory()
    mem.remember("I like jazz")
    report = mem.reflect()
    assert report.summary() == "no issues detected"
    assert report.is_empty()


def test_reflect_dry_run_does_not_mutate():
    mem = AgentMemory()
    mem.remember("User likes jazz", subject="user")
    for content in ("coffee", "tea", "matcha", "water"):
        mem.remember(f"User likes {content}", subject="user")
    pre = mem.store.by_type("preference")[0].metadata.copy()
    mem.reflect(dry_run=True, drift_min_replaces=2)
    post = mem.store.by_type("preference")[0].metadata
    # Drift annotation should not have been written under dry_run.
    assert "drift_flags" not in post


def test_reflect_summary_requires_llm_client():
    mem = AgentMemory()
    with pytest.raises(RuntimeError, match="llm_client"):
        mem.reflect(include_summary=True)


def test_reflect_with_llm_client_runs_summary():
    mem = AgentMemory(llm_client=FakeClient("summary text"))
    # No stale memories to summarize, but the call should still succeed.
    report = mem.reflect(include_summary=True)
    assert isinstance(report, AgentMemoryReflection)


# ── forget ───────────────────────────────────────────────────────────────────
def test_forget_removes_memory():
    mem = AgentMemory()
    [m] = mem.remember("I like jazz")
    assert mem.forget(m.id) is True
    assert mem.forget(m.id) is False  # idempotent
    assert len(mem) == 0


# ── LLM extractor integration ────────────────────────────────────────────────
def test_works_with_llm_extractor():
    import json
    raw = json.dumps([
        {"type": "claim", "content": "X improves Y", "confidence": 0.9,
         "source": {"document_id": "paper.pdf"}},
    ])
    mem = AgentMemory(
        profile="research_paper",
        extractor=LLMExtractor(FakeClient(raw), profile=DomainProfile.builtin("research_paper")),
    )
    added = mem.remember("any text")
    assert len(added) == 1
    assert added[0].type == "claim"


# ── End-to-end debugging story ───────────────────────────────────────────────
def test_full_debug_loop_surfaces_drift():
    """The 'debugging hallucinating agents' use case in one test."""
    mem = AgentMemory()
    mem.remember("I prefer concise answers", subject="user")
    mem.remember("I prefer detailed answers", subject="user")
    mem.remember("I prefer concise answers", subject="user")
    mem.remember("I prefer detailed answers", subject="user")

    report = mem.reflect(drift_min_replaces=2)
    assert report.drift_records, "drift should be detected"
    assert "preference" in report.summary().lower() or "unstable" in report.summary().lower()

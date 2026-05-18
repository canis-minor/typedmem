"""HTTP server (v0.7+) — endpoint coverage via FastAPI TestClient.

Skipped unless the ``server`` extra is installed (fastapi + pydantic).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from typedmem import (  # noqa: E402
    ConflictPolicy,
    DomainProfile,
    InMemoryStore,
    Memory,
    MemoryType,
    PolicyEngine,
    TypePolicy,
)
from typedmem.server import ServerConfig, create_app  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────
def _client(store=None, *, api_token="secret", **cfg_kwargs) -> TestClient:
    # NOTE: ``store if store is not None`` not ``store or`` — InMemoryStore
    # is falsy when empty (__len__ == 0) so the truthy-fallback discards it.
    if store is None:
        store = InMemoryStore()
    cfg = ServerConfig(api_token=api_token, **cfg_kwargs)
    return TestClient(create_app(store, config=cfg))


def _h(token="secret"):
    return {"Authorization": f"Bearer {token}"}


# ── Ops endpoints (no auth needed) ──────────────────────────────────────────
def test_healthz_no_auth():
    r = _client().get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_version_no_auth():
    r = _client().get("/v1/version")
    assert r.status_code == 200
    body = r.json()
    assert "typedmem" in body and "instance" in body


# ── Auth ────────────────────────────────────────────────────────────────────
def test_missing_token_401():
    r = _client().get("/v1/memories")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthenticated"


def test_wrong_token_401():
    r = _client().get("/v1/memories", headers=_h("wrong"))
    assert r.status_code == 401


def test_no_auth_mode_allows_everything():
    """If api_token and identity_audience are both None, no auth is required."""
    store = InMemoryStore()
    app = create_app(store, config=ServerConfig())
    c = TestClient(app)
    r = c.get("/v1/memories")
    assert r.status_code == 200


# ── Memories CRUD ───────────────────────────────────────────────────────────
def test_add_get_delete_memory():
    c = _client()
    body = {
        "memory": {"type": "fact", "content": "sky is blue", "subject": "sky"},
        "event_source": "user",
        "event_source_name": "test",
    }
    r = c.post("/v1/memories", json=body, headers=_h())
    assert r.status_code == 200
    mid = r.json()["id"]

    r = c.get(f"/v1/memories/{mid}", headers=_h())
    assert r.status_code == 200
    assert r.json()["content"] == "sky is blue"

    r = c.delete(
        f"/v1/memories/{mid}?event_source=user&event_source_name=test",
        headers=_h(),
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": mid}

    r = c.get(f"/v1/memories/{mid}", headers=_h())
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"


def test_delete_missing_404():
    c = _client()
    r = c.delete("/v1/memories/nonexistent", headers=_h())
    assert r.status_code == 404


def test_list_memories_filters():
    store = InMemoryStore()
    store.add(Memory(MemoryType.FACT, "alpha", subject="x"))
    store.add(Memory(MemoryType.GOAL, "beta", subject="y"))
    c = _client(store)

    r = c.get("/v1/memories", headers=_h())
    assert r.status_code == 200 and len(r.json()) == 2

    r = c.get("/v1/memories?type=goal", headers=_h())
    assert r.status_code == 200
    assert {m["content"] for m in r.json()} == {"beta"}

    r = c.get("/v1/memories?limit=1", headers=_h())
    assert len(r.json()) == 1


def test_workspace_isolation_via_query_param():
    """Multi-tenancy model: client passes workspace per request."""
    store = InMemoryStore()
    c = _client(store)
    for ws in ("alice", "bob"):
        c.post(
            "/v1/memories",
            json={"memory": {"type": "fact", "content": f"{ws} thing", "workspace": ws}},
            headers=_h(),
        )
    r = c.get("/v1/memories?workspace=alice", headers=_h())
    assert {m["content"] for m in r.json()} == {"alice thing"}
    r = c.get("/v1/memories?workspace=bob", headers=_h())
    assert {m["content"] for m in r.json()} == {"bob thing"}


# ── Recall ──────────────────────────────────────────────────────────────────
def test_recall_returns_scored_memories():
    store = InMemoryStore()
    store.add(Memory(MemoryType.FACT, "the sky is blue", subject="sky"))
    store.add(Memory(MemoryType.FACT, "grass is green",  subject="grass"))
    c = _client(store)

    r = c.post("/v1/recall", json={"query": "sky color", "limit": 5}, headers=_h())
    assert r.status_code == 200
    hits = r.json()
    assert hits and all("score" in h and "memory" in h for h in hits)
    assert hits[0]["memory"]["content"] == "the sky is blue"


# ── Timeline ────────────────────────────────────────────────────────────────
def test_memory_history_endpoint():
    c = _client()
    body = {"memory": {"type": "fact", "content": "x"},
            "event_source": "agent", "event_source_name": "bot"}
    r = c.post("/v1/memories", json=body, headers=_h())
    mid = r.json()["id"]

    r = c.get(f"/v1/memories/{mid}/history", headers=_h())
    assert r.status_code == 200
    events = r.json()
    assert len(events) == 1
    assert events[0]["action"] == "added"
    assert events[0]["source"] == "agent"
    assert events[0]["source_name"] == "bot"


def test_timeline_source_filter():
    store = InMemoryStore()
    c = _client(store)
    c.post("/v1/memories",
           json={"memory": {"type": "fact", "content": "x"}, "event_source": "user"},
           headers=_h())
    c.post("/v1/memories",
           json={"memory": {"type": "fact", "content": "y"}, "event_source": "agent"},
           headers=_h())

    r = c.get("/v1/timeline?source=user", headers=_h())
    assert all(e["source"] == "user" for e in r.json())
    assert len(r.json()) == 1

    r = c.get("/v1/timeline?source=agent", headers=_h())
    assert all(e["source"] == "agent" for e in r.json())


def test_changed_since_returns_only_newer_events():
    store = InMemoryStore()
    c = _client(store)
    c.post("/v1/memories", json={"memory": {"type": "fact", "content": "first"}},
           headers=_h())
    cutoff = datetime.now(timezone.utc)
    # Need to make sure later event timestamp > cutoff
    import time; time.sleep(0.01)
    c.post("/v1/memories", json={"memory": {"type": "fact", "content": "second"}},
           headers=_h())

    # Pass `since` via params= so httpx URL-encodes the `+` in the offset.
    r = c.get("/v1/changed-since", params={"since": cutoff.isoformat()},
              headers=_h())
    assert r.status_code == 200
    events = r.json()
    assert len(events) == 1
    assert all(e["timestamp"] > cutoff.isoformat() for e in events)


# ── Reflect / contradictions ────────────────────────────────────────────────
def test_contradictions_endpoint():
    eng = PolicyEngine()
    eng.policies[MemoryType.FACT.value] = TypePolicy(None, False, ConflictPolicy.FLAG)
    store = InMemoryStore(eng)
    store.add(Memory(MemoryType.FACT, "X", subject="t"))
    store.add(Memory(MemoryType.FACT, "Y", subject="t"))
    c = _client(store)

    r = c.get("/v1/contradictions", headers=_h())
    assert r.status_code == 200
    clusters = r.json()
    assert len(clusters) == 1
    assert {m["content"] for m in clusters[0]} == {"X", "Y"}


def test_reflect_returns_structured_report():
    c = _client()
    r = c.post("/v1/reflect", json={"dry_run": True}, headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert {"contradictions", "drift_records", "goal_records"} <= body.keys()


def test_workspaces_endpoint():
    store = InMemoryStore()
    store.add(Memory(MemoryType.FACT, "a", workspace="alice"))
    store.add(Memory(MemoryType.FACT, "b", workspace="bob"))
    c = _client(store)
    r = c.get("/v1/workspaces", headers=_h())
    assert r.status_code == 200
    assert set(r.json()) == {"alice", "bob"}


# ── Error translation ───────────────────────────────────────────────────────
def test_profile_rejection_returns_422():
    """Profile-validated stores must reject invalid types with a structured
    422, not a 500."""
    profile = DomainProfile.builtin("personal")
    policy = PolicyEngine.from_profile(profile)
    store = InMemoryStore(policy=policy, profile=profile)
    c = _client(store)

    r = c.post(
        "/v1/memories",
        json={"memory": {"type": "this_type_does_not_exist", "content": "x"}},
        headers=_h(),
    )
    assert r.status_code == 422
    body = r.json()
    assert body.get("code") == "profile_validation_error" or \
           body.get("detail", {}).get("code") == "profile_validation_error"


def test_invalid_event_source_returns_validation_error():
    c = _client()
    r = c.post(
        "/v1/memories",
        json={"memory": {"type": "fact", "content": "x"}, "event_source": "BAD"},
        headers=_h(),
    )
    # Pydantic catches this at body-validation time → 422
    assert r.status_code == 422


# ── CORS ────────────────────────────────────────────────────────────────────
def test_cors_origin_header_when_configured():
    store = InMemoryStore()
    app = create_app(store, config=ServerConfig(api_token="secret", cors_origin="*"))
    c = TestClient(app)
    r = c.options(
        "/v1/memories",
        headers={"Origin": "https://example.com",
                 "Access-Control-Request-Method": "GET"},
    )
    # Starlette CORSMiddleware returns 200 with the right headers
    assert "access-control-allow-origin" in {h.lower() for h in r.headers.keys()}

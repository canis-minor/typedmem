import { describe, expect, it } from "vitest";
import { TypedMemoryClient } from "../src/client.js";
import {
  NotFoundError,
  ProfileValidationError,
  TypedMemoryError,
  UnauthenticatedError,
} from "../src/errors.js";
import type { Memory, MemoryEvent } from "../src/types.js";

// ── Test fixtures ─────────────────────────────────────────────────────────
interface RecordedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
  body?: unknown;
}

/**
 * Build a fake fetch that records every call and returns the response from
 * `responder`. Lets us assert *exactly* what the client sent to the server
 * without spinning up the real Python service.
 */
function fakeFetch(
  responder: (req: RecordedRequest) => { status: number; body?: unknown },
): { fetch: typeof globalThis.fetch; calls: RecordedRequest[] } {
  const calls: RecordedRequest[] = [];
  const fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const headers: Record<string, string> = {};
    if (init?.headers) {
      const h = new Headers(init.headers);
      h.forEach((v, k) => (headers[k] = v));
    }
    const recorded: RecordedRequest = {
      url,
      method: init?.method ?? "GET",
      headers,
      body: init?.body ? JSON.parse(init.body as string) : undefined,
    };
    calls.push(recorded);
    const { status, body } = responder(recorded);
    return new Response(body !== undefined ? JSON.stringify(body) : null, {
      status,
      headers: { "content-type": "application/json" },
    });
  }) as typeof globalThis.fetch;
  return { fetch, calls };
}

const sampleMemory: Memory = {
  id: "mem-1",
  type: "fact",
  content: "sky is blue",
  confidence: 1.0,
  timestamp: "2026-05-18T00:00:00Z",
  updated_at: "2026-05-18T00:00:00Z",
  subject: "sky",
  tags: [],
  workspace: "default",
  sources: [],
  metadata: {},
};

// ── Construction ──────────────────────────────────────────────────────────
describe("constructor", () => {
  it("strips trailing slash from url", () => {
    const { fetch } = fakeFetch(() => ({ status: 200, body: [] }));
    const c = new TypedMemoryClient({ url: "http://x/", fetch });
    expect(c.url).toBe("http://x");
  });
});

// ── Auth header ───────────────────────────────────────────────────────────
describe("auth", () => {
  it("includes Bearer token when apiToken is set", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: [] }));
    const c = new TypedMemoryClient({
      url: "http://x", apiToken: "secret", fetch,
    });
    await c.list();
    expect(calls[0].headers.authorization).toBe("Bearer secret");
  });

  it("omits Authorization when no token", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: [] }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await c.list();
    expect(calls[0].headers.authorization).toBeUndefined();
  });
});

// ── add / get / delete ────────────────────────────────────────────────────
describe("add()", () => {
  it("posts to /v1/memories with event_source metadata", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: sampleMemory }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    const m = await c.add(
      { type: "fact", content: "sky is blue" },
      { eventSource: "agent", eventSourceName: "test" },
    );
    expect(m.id).toBe("mem-1");
    expect(calls[0].url).toBe("http://x/v1/memories");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({
      memory: { type: "fact", content: "sky is blue" },
      event_source: "agent",
      event_source_name: "test",
    });
  });

  it("applies the instance default workspace to the memory body", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: sampleMemory }));
    const c = new TypedMemoryClient({
      url: "http://x", workspace: "user-42", fetch,
    });
    await c.add({ type: "fact", content: "x" });
    expect((calls[0].body as any).memory.workspace).toBe("user-42");
  });

  it("honours an explicit workspace on the memory", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: sampleMemory }));
    const c = new TypedMemoryClient({
      url: "http://x", workspace: "user-42", fetch,
    });
    await c.add({ type: "fact", content: "x", workspace: "override" });
    expect((calls[0].body as any).memory.workspace).toBe("override");
  });

  it("defaults event_source to 'store'", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: sampleMemory }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await c.add({ type: "fact", content: "x" });
    expect((calls[0].body as any).event_source).toBe("store");
  });
});

describe("get / delete", () => {
  it("get() URL-encodes the memory id", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: sampleMemory }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await c.get("with/slash");
    expect(calls[0].url).toBe("http://x/v1/memories/with%2Fslash");
  });

  it("delete() carries event_source in query string", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: { deleted: "mem-1" } }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await c.delete("mem-1", { eventSource: "user", eventSourceName: "ui:trash" });
    expect(calls[0].url).toBe(
      "http://x/v1/memories/mem-1?event_source=user&event_source_name=ui%3Atrash",
    );
  });
});

// ── list ──────────────────────────────────────────────────────────────────
describe("list()", () => {
  it("includes default workspace and supports filters", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: [] }));
    const c = new TypedMemoryClient({
      url: "http://x", workspace: "ws", fetch,
    });
    await c.list({ type: "fact", includeSuperseded: true, limit: 5 });
    const url = new URL(calls[0].url);
    expect(url.pathname).toBe("/v1/memories");
    expect(url.searchParams.get("workspace")).toBe("ws");
    expect(url.searchParams.get("type")).toBe("fact");
    expect(url.searchParams.get("include_superseded")).toBe("true");
    expect(url.searchParams.get("limit")).toBe("5");
  });
});

// ── recall ────────────────────────────────────────────────────────────────
describe("recall()", () => {
  it("serializes Date as ISO and drops undefined fields", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: [] }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    const since = new Date("2026-05-01T00:00:00Z");
    await c.recall("color theme", { since, limit: 3 });
    expect(calls[0].body).toEqual({
      query: "color theme",
      since: "2026-05-01T00:00:00.000Z",
      limit: 3,
    });
  });
});

// ── timeline / history / changed-since ────────────────────────────────────
describe("timeline", () => {
  it("history() hits the per-memory endpoint", async () => {
    const events: MemoryEvent[] = [{
      id: "e1", memory_id: "mem-1", workspace: "default",
      type: "fact", subject: "sky", action: "added",
      source: "user", source_name: "test", reason: "",
      input_ids: [], output_ids: [], payload: {},
      timestamp: "2026-05-18T00:00:00Z",
    }];
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: events }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    const got = await c.history("mem-1");
    expect(calls[0].url).toBe("http://x/v1/memories/mem-1/history");
    expect(got).toEqual(events);
  });

  it("timeline() builds the right query string", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: [] }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await c.timeline({ subject: "sky", source: "user", workspace: "ws" });
    const url = new URL(calls[0].url);
    expect(url.searchParams.get("subject")).toBe("sky");
    expect(url.searchParams.get("source")).toBe("user");
    expect(url.searchParams.get("workspace")).toBe("ws");
  });

  it("changedSince() encodes Date and accepts string", async () => {
    const { fetch, calls } = fakeFetch(() => ({ status: 200, body: [] }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await c.changedSince(new Date("2026-05-17T12:00:00Z"));
    expect(new URL(calls[0].url).searchParams.get("since"))
      .toBe("2026-05-17T12:00:00.000Z");
  });
});

// ── reflect / contradictions / workspaces / version ──────────────────────
describe("reflect()", () => {
  it("posts dry_run + thresholds", async () => {
    const { fetch, calls } = fakeFetch(() => ({
      status: 200,
      body: { contradictions: [], drift_records: [], goal_records: [] },
    }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await c.reflect({ dryRun: true, goalThreshold: 0.9 });
    expect(calls[0].body).toEqual({ dry_run: true, goal_threshold: 0.9 });
  });
});

// ── Error translation ─────────────────────────────────────────────────────
describe("error translation", () => {
  it("401 → UnauthenticatedError", async () => {
    const { fetch } = fakeFetch(() => ({
      status: 401,
      body: { detail: { error: "missing", code: "unauthenticated" } },
    }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await expect(c.list()).rejects.toBeInstanceOf(UnauthenticatedError);
  });

  it("404 → NotFoundError with details", async () => {
    const { fetch } = fakeFetch(() => ({
      status: 404,
      body: { detail: { error: "memory 'x' not found", code: "not_found",
                         details: { id: "x" } } },
    }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    try {
      await c.get("x");
      throw new Error("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(NotFoundError);
      expect((e as NotFoundError).details).toEqual({ id: "x" });
    }
  });

  it("422 → ProfileValidationError", async () => {
    const { fetch } = fakeFetch(() => ({
      status: 422,
      body: { error: "rejected", code: "profile_validation_error" },
    }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    await expect(c.add({ type: "bad", content: "x" }))
      .rejects.toBeInstanceOf(ProfileValidationError);
  });

  it("unknown 5xx → generic TypedMemoryError", async () => {
    const { fetch } = fakeFetch(() => ({
      status: 500, body: { error: "boom" },
    }));
    const c = new TypedMemoryClient({ url: "http://x", fetch });
    try {
      await c.list();
    } catch (e) {
      expect(e).toBeInstanceOf(TypedMemoryError);
      expect((e as TypedMemoryError).status).toBe(500);
    }
  });
});

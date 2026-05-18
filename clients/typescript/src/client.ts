import { errorFromResponse } from "./errors.js";
import type {
  EventSource,
  Memory,
  MemoryEvent,
  MemoryInput,
  ReflectReport,
  ScoredMemory,
  VersionInfo,
} from "./types.js";

export interface TypedMemoryClientOptions {
  /** Base URL of the typedmem server (no trailing slash). */
  url: string;
  /** Bearer token for ``Authorization`` header. Omit for no-auth mode. */
  apiToken?: string;
  /** Default workspace applied to add/list/recall/timeline when not overridden. */
  workspace?: string;
  /**
   * Override fetch (for tests or non-browser environments without global
   * fetch). Defaults to ``globalThis.fetch``. Node 18+ has it built-in.
   */
  fetch?: typeof globalThis.fetch;
}

export interface AddOptions {
  eventSource?: EventSource;
  eventSourceName?: string | null;
}

export interface ListOptions {
  workspace?: string;
  type?: string;
  includeSuperseded?: boolean;
  limit?: number;
}

export interface RecallOptions {
  limit?: number;
  types?: string[];
  tags?: string[];
  since?: Date | string;
  workspace?: string;
  includeSuperseded?: boolean;
}

export interface TimelineOptions {
  subject?: string;
  type?: string;
  workspace?: string;
  source?: EventSource;
}

export interface DeleteOptions {
  eventSource?: EventSource;
  eventSourceName?: string | null;
}

export interface ReflectOptions {
  workspace?: string;
  dryRun?: boolean;
  driftMinReplaces?: number;
  driftWindowDays?: number;
  goalThreshold?: number;
}

/**
 * HTTP client for a TypedMemory server.
 *
 * ```ts
 * const tm = new TypedMemoryClient({
 *   url: 'http://localhost:8080',
 *   apiToken: process.env.TYPEDMEM_TOKEN,
 *   workspace: `user-${userId}`,
 * });
 *
 * const m = await tm.add(
 *   { type: 'observation', content: 'first steps today', subject: 'milestone' },
 *   { eventSource: 'user', eventSourceName: 'my-app:entry' }
 * );
 * for (const e of await tm.history(m.id)) console.log(e.action, e.source);
 * ```
 */
export class TypedMemoryClient {
  readonly url: string;
  readonly workspace: string | undefined;
  private readonly apiToken: string | undefined;
  private readonly fetchImpl: typeof globalThis.fetch;

  constructor(opts: TypedMemoryClientOptions) {
    this.url = opts.url.replace(/\/+$/, "");
    this.apiToken = opts.apiToken;
    this.workspace = opts.workspace;
    this.fetchImpl = opts.fetch ?? globalThis.fetch;
    if (!this.fetchImpl) {
      throw new TypeError(
        "No fetch implementation available. Pass `fetch: yourFetch` or run on Node 18+."
      );
    }
  }

  // ── Memories ────────────────────────────────────────────────────────────
  async add(memory: MemoryInput, opts: AddOptions = {}): Promise<Memory> {
    const body = {
      memory: { workspace: this.workspace, ...memory },
      event_source: opts.eventSource ?? "store",
      event_source_name: opts.eventSourceName ?? null,
    };
    return this.request<Memory>("POST", "/v1/memories", { body });
  }

  async get(memoryId: string): Promise<Memory> {
    return this.request<Memory>("GET", `/v1/memories/${encodeURIComponent(memoryId)}`);
  }

  async delete(memoryId: string, opts: DeleteOptions = {}): Promise<void> {
    const query = new URLSearchParams();
    if (opts.eventSource) query.set("event_source", opts.eventSource);
    if (opts.eventSourceName) query.set("event_source_name", opts.eventSourceName);
    const qs = query.toString();
    await this.request<{ deleted: string }>(
      "DELETE",
      `/v1/memories/${encodeURIComponent(memoryId)}${qs ? "?" + qs : ""}`,
    );
  }

  async list(opts: ListOptions = {}): Promise<Memory[]> {
    const query = new URLSearchParams();
    const ws = opts.workspace ?? this.workspace;
    if (ws !== undefined) query.set("workspace", ws);
    if (opts.type) query.set("type", opts.type);
    if (opts.includeSuperseded) query.set("include_superseded", "true");
    if (opts.limit) query.set("limit", String(opts.limit));
    return this.request<Memory[]>("GET", "/v1/memories?" + query.toString());
  }

  // ── Recall ──────────────────────────────────────────────────────────────
  async recall(query: string, opts: RecallOptions = {}): Promise<ScoredMemory[]> {
    const body = {
      query,
      limit: opts.limit,
      types: opts.types,
      tags: opts.tags,
      since: opts.since instanceof Date ? opts.since.toISOString() : opts.since,
      workspace: opts.workspace ?? this.workspace,
      include_superseded: opts.includeSuperseded,
    };
    // Drop undefined keys so server defaults apply.
    const compact = Object.fromEntries(
      Object.entries(body).filter(([, v]) => v !== undefined),
    );
    return this.request<ScoredMemory[]>("POST", "/v1/recall", { body: compact });
  }

  // ── Timeline ────────────────────────────────────────────────────────────
  async history(memoryId: string): Promise<MemoryEvent[]> {
    return this.request<MemoryEvent[]>(
      "GET",
      `/v1/memories/${encodeURIComponent(memoryId)}/history`,
    );
  }

  async timeline(opts: TimelineOptions = {}): Promise<MemoryEvent[]> {
    const query = new URLSearchParams();
    if (opts.subject) query.set("subject", opts.subject);
    if (opts.type) query.set("type", opts.type);
    const ws = opts.workspace ?? this.workspace;
    if (ws !== undefined) query.set("workspace", ws);
    if (opts.source) query.set("source", opts.source);
    return this.request<MemoryEvent[]>("GET", "/v1/timeline?" + query.toString());
  }

  async changedSince(since: Date | string): Promise<MemoryEvent[]> {
    const isoString = since instanceof Date ? since.toISOString() : since;
    const query = new URLSearchParams({ since: isoString });
    return this.request<MemoryEvent[]>("GET", "/v1/changed-since?" + query.toString());
  }

  // ── Reflect ─────────────────────────────────────────────────────────────
  async reflect(opts: ReflectOptions = {}): Promise<ReflectReport> {
    const body = {
      workspace: opts.workspace ?? this.workspace,
      dry_run: opts.dryRun,
      drift_min_replaces: opts.driftMinReplaces,
      drift_window_days: opts.driftWindowDays,
      goal_threshold: opts.goalThreshold,
    };
    const compact = Object.fromEntries(
      Object.entries(body).filter(([, v]) => v !== undefined),
    );
    return this.request<ReflectReport>("POST", "/v1/reflect", { body: compact });
  }

  async contradictions(opts: { workspace?: string } = {}): Promise<Memory[][]> {
    const query = new URLSearchParams();
    const ws = opts.workspace ?? this.workspace;
    if (ws !== undefined) query.set("workspace", ws);
    const qs = query.toString();
    return this.request<Memory[][]>(
      "GET",
      "/v1/contradictions" + (qs ? "?" + qs : ""),
    );
  }

  // ── Ops ─────────────────────────────────────────────────────────────────
  async workspaces(): Promise<string[]> {
    return this.request<string[]>("GET", "/v1/workspaces");
  }

  async version(): Promise<VersionInfo> {
    return this.request<VersionInfo>("GET", "/v1/version");
  }

  async healthz(): Promise<{ status: string }> {
    return this.request<{ status: string }>("GET", "/healthz");
  }

  // ── Internal ────────────────────────────────────────────────────────────
  private async request<T>(
    method: string,
    path: string,
    opts: { body?: unknown } = {},
  ): Promise<T> {
    const headers: Record<string, string> = {};
    if (this.apiToken) headers["Authorization"] = `Bearer ${this.apiToken}`;
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";

    const response = await this.fetchImpl(this.url + path, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });

    if (!response.ok) {
      let body: unknown = undefined;
      try {
        body = await response.json();
      } catch {
        body = await response.text().catch(() => undefined);
      }
      throw errorFromResponse(response.status, body);
    }

    // No-content responses (currently none, but defensive)
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
}

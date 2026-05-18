# typedmem-client

TypeScript client for [TypedMemory](https://github.com/canis-minor/typedmem) — **contract-driven memory for AI agents.**

Typed schemas, explicit conflict policies, structured provenance, typed event timeline — all over a REST API. Use this when your app isn't Python; the client talks to a `typedmem serve` HTTP server, same surface as the Python library.

## Install

```bash
npm install typedmem-client
```

Zero runtime dependencies. Node 18+ (native `fetch`) or any modern browser.

## Quickstart

Run the server somewhere reachable:

```bash
pip install 'typedmem[server]'
typedmem serve --store agent.db --api-token $(openssl rand -hex 32)
```

Then in your TypeScript code:

```ts
import { TypedMemoryClient } from "typedmem-client";

const tm = new TypedMemoryClient({
  url: "http://localhost:8080",
  apiToken: process.env.TYPEDMEM_TOKEN,
  workspace: `user-${userId}`,    // multi-tenant isolation
});

// Add a memory
const m = await tm.add(
  { type: "observation", content: "first steps today", subject: "milestone:walking" },
  { eventSource: "user", eventSourceName: "my-app:entry" },
);

// Recall — server-side semantic match
for (const hit of await tm.recall("walking development", { limit: 5 })) {
  console.log(hit.score, hit.memory.content);
}

// Per-memory timeline
for (const e of await tm.history(m.id)) {
  console.log(e.timestamp, e.source, e.action, e.reason);
}

// Canonical change feed for syncing downstream
const since = new Date(Date.now() - 24 * 3600 * 1000);
for (const e of await tm.changedSince(since)) {
  ship(e);
}

// Reflection (contradictions + drift + goal resolution)
const report = await tm.reflect({ dryRun: false, goalThreshold: 0.85 });
console.log(`${report.contradictions.length} contradiction cluster(s)`);
```

## API

All methods are async. Errors throw typed subclasses of `TypedMemoryError` so you can branch on `err.code` without parsing strings.

### Memories

| Method | Calls |
|---|---|
| `add(memory, opts?)` | `POST /v1/memories` |
| `get(id)` | `GET /v1/memories/:id` |
| `delete(id, opts?)` | `DELETE /v1/memories/:id` |
| `list(opts?)` | `GET /v1/memories` |

### Recall

| Method | Calls |
|---|---|
| `recall(query, opts?)` | `POST /v1/recall` — server-side hashing-embedder semantic match |

### Timeline (v0.6+ event log)

| Method | Calls |
|---|---|
| `history(id)` | `GET /v1/memories/:id/history` |
| `timeline(opts?)` | `GET /v1/timeline?subject=&type=&workspace=&source=` |
| `changedSince(date)` | `GET /v1/changed-since?since=<ISO 8601>` |

### Reflection

| Method | Calls |
|---|---|
| `reflect(opts?)` | `POST /v1/reflect` — contradictions + drift + goal resolution |
| `contradictions(opts?)` | `GET /v1/contradictions` |

### Ops

| Method | Calls |
|---|---|
| `workspaces()` | `GET /v1/workspaces` |
| `version()` | `GET /v1/version` |
| `healthz()` | `GET /healthz` |

## Multi-tenancy

The recommended pattern is one workspace per end-user:

```ts
const tm = new TypedMemoryClient({
  url: "...",
  apiToken: "...",
  workspace: `user-${firebaseUid}`,  // applied as default to add/list/recall/timeline
});
```

Per-call override is also supported: `tm.list({ workspace: "other" })`.

The server **trusts the workspace value the client sends**. Your auth layer (the API token, or Cloud Run IAM) gates whether the caller can talk to the server at all; *which* workspace they use is up to your client code.

## Auth modes

| Server flags | Client config |
|---|---|
| `--api-token T` | `apiToken: "T"` |
| `--identity-audience https://...` (Cloud Run IAM) | Pass a Google-signed ID token as `apiToken` (use `google-auth-library` to fetch it) |
| neither (local-dev only) | `apiToken: undefined` |

For Cloud Run service-to-service:

```ts
// In a Cloud Run service calling typedmem-on-Cloud-Run
import { GoogleAuth } from "google-auth-library";

const typedmemUrl = "https://typedmem-xxxxxx-uc.a.run.app";
const auth = new GoogleAuth();
const client = await auth.getIdTokenClient(typedmemUrl);
const tokenResponse = await client.getRequestHeaders(typedmemUrl);
const token = tokenResponse.Authorization.replace(/^Bearer /, "");

const tm = new TypedMemoryClient({
  url: typedmemUrl,
  apiToken: token,         // refresh per-call; tokens are short-lived
  workspace: `user-${userId}`,
});
```

In practice you'll wrap this in a helper that refreshes the token before each request (or per-minute, since they last an hour).

## Errors

```ts
import {
  TypedMemoryError,
  NotFoundError,
  UnauthenticatedError,
  ProfileValidationError,
} from "typedmem-client";

try {
  await tm.get(maybeMissing);
} catch (e) {
  if (e instanceof NotFoundError) {
    // 404 — memory id wasn't there
  } else if (e instanceof UnauthenticatedError) {
    // 401 — refresh token and retry
  } else if (e instanceof ProfileValidationError) {
    // 422 — fix the memory shape; details have field errors
    console.error(e.details);
  } else if (e instanceof TypedMemoryError) {
    // unknown server-side error
    console.error(e.status, e.code, e.message);
  } else {
    throw e;             // network error
  }
}
```

## Compatibility

| Client | TypedMemory server |
|---|---|
| 0.7.x | 0.7.x — both pin the `/v1/` wire format |

The client's major version tracks the server's wire-format version. v0.7 speaks `/v1/`. If a future server adds breaking wire changes (`/v2/`), there will be a new major client.

## License

MIT

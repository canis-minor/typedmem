# Server (HTTP / v0.7+)

TypedMemory ships as a Python library, but starting with v0.7 it can also run
as an HTTP service. The server exposes the existing Python surface under
`/v1/`, so any language with a JSON client can use it — TypeScript, Go, Rust,
shell scripts, anything.

The server is an **optional extra**. Default `pip install typedmem` stays
zero-dependency. Install with the extra to get it:

```bash
pip install 'typedmem[server]'
```

For Cloud Run deploys with Google ID-token auth:

```bash
pip install 'typedmem[gcp]'   # adds google-auth on top of [server]
```

## Quickstart — local

```bash
typedmem --store agent.db serve --api-token dev-secret
# typedmem serve  store=agent.db  workspace=default  auth=bearer-token  → http://0.0.0.0:8080/
```

Note the flag order: `--store`, `--workspace`, `--profile`, and `--profile-file` are **global** flags shared with the rest of the `typedmem` CLI, so they come *before* the subcommand. Or set them via env: `TYPEDMEM_DB=agent.db typedmem serve --api-token …`.

In another terminal:

```bash
curl -H 'Authorization: Bearer dev-secret' \
  -X POST http://localhost:8080/v1/memories \
  -H 'content-type: application/json' \
  -d '{"memory": {"type": "fact", "content": "the sky is blue"},
       "event_source": "user", "event_source_name": "curl"}'
```

Interactive API docs are auto-generated at <http://localhost:8080/docs>.

## Endpoints

All endpoints under `/v1/` require auth if configured. `/healthz` and
`/v1/version` always bypass auth for Cloud Run health checks and curl probes.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/v1/version` | typedmem version + instance name |
| `POST` | `/v1/memories` | Add a memory; tag with `event_source` / `event_source_name` |
| `GET` | `/v1/memories/{id}` | Fetch one memory |
| `DELETE` | `/v1/memories/{id}` | Delete; pass `?event_source=&event_source_name=` |
| `GET` | `/v1/memories` | List with `?workspace=&type=&include_superseded=&limit=` |
| `POST` | `/v1/recall` | Semantic recall (server-side embedder) |
| `GET` | `/v1/memories/{id}/history` | Every event for one memory, oldest first |
| `GET` | `/v1/timeline` | Filter the event log: `?subject=&type=&workspace=&source=` |
| `GET` | `/v1/changed-since` | Canonical change feed; `?since=<ISO 8601>` |
| `POST` | `/v1/reflect` | Run the evolver pipeline (contradictions + drift + goals) |
| `GET` | `/v1/contradictions` | Just the contradiction clusters |
| `GET` | `/v1/workspaces` | List known workspaces |

Wire format mirrors `Memory.to_dict()` / `MemoryEvent.to_dict()` 1:1. `EventSource`
values are `"store" | "evolver" | "agent" | "user" | "system"`.

## Auth

Three modes, picked by what you pass at startup:

| `--api-token` | `--identity-audience` | Behaviour |
|---|---|---|
| unset | unset | **No auth.** Local dev only. Every request passes. |
| set | unset | Bearer token required: `Authorization: Bearer <token>` |
| unset | set | Google ID token required (Cloud Run service-to-service IAM) |
| set | set | **Either** accepted — production + local dev side by side |

`--api-token` can also come from `TYPEDMEM_API_TOKEN` env var. The token
comparison is constant-time. Choose a long random token (`openssl rand -hex 32`).

Google ID-token validation needs the `[gcp]` extra (which adds `google-auth`).
The `--identity-audience` is usually the Cloud Run service URL itself, e.g.
`https://typedmem-xxxxxx-uc.a.run.app`. Google validates the token's signature,
expiry, and audience claim; expired or wrong-audience tokens are rejected.

## Multi-tenancy

The server is single-store: one server process serves one SQLite database
and one profile. Multi-tenancy is by **workspace**: every endpoint that
touches data takes an optional `workspace=` query param (or, for `POST`
endpoints, a `workspace` field in the memory body).

The recommended pattern is one workspace per end-user, derived from your
own auth system. For ai-life-tracker on Firebase, that's
`workspace=f"user-{firebase_uid}"`.

The server **trusts the workspace value passed by the caller**. Your auth
layer (the API token or the Cloud Run IAM check) gates *whether* the caller
can use the server at all; *which* workspace they use is up to your client
code. If you need server-enforced workspace binding (e.g. one API token per
end-user), that's a v0.7.x feature.

## Profile binding

One profile per server, set at startup with `--profile personal` (or omit
to run schema-less). The profile is enforced for all writes — incoming
memories with declared-but-invalid types are rejected with HTTP 422 and
`code: "profile_validation_error"`.

If you need different profiles per tenant, run one server per profile.

## Embedder

The server runs the hashing embedder server-side (`HashingEmbeddingProvider`).
Recall sends just the query text over the wire; the server scores against
stored memories. The hashing embedder is deterministic given `--dim`, so
all clients/instances against the same store see consistent scores.

Sentence-transformer support is v0.7.x; track [issue
TBD](https://github.com/canis-minor/typedmem/issues).

## Deploy: Cloud Run + GCS FUSE

Cloud Run is stateless — the container filesystem is wiped on restart, so
**SQLite on the local filesystem will lose data**. The supported v0.7.0
pattern is GCS FUSE: mount a Cloud Storage bucket into the container, store
the SQLite file there.

### 1. Create a bucket and grant the service account access

```bash
gcloud storage buckets create gs://my-typedmem-data \
  --location us-central1 --uniform-bucket-level-access

# Service account that the Cloud Run service runs as
SA="typedmem-runner@my-project.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding my-project \
  --member "serviceAccount:$SA" --role roles/storage.objectAdmin
```

### 2. Deploy

```bash
gcloud run deploy typedmem \
  --project my-project --region us-central1 \
  --image ghcr.io/canis-minor/typedmem:0.7.0 \
  --service-account "$SA" \
  --max-instances 1 \
  --add-volume name=data,type=cloud-storage,bucket=my-typedmem-data \
  --add-volume-mount volume=data,mount-path=/data \
  --set-env-vars TYPEDMEM_API_TOKEN=$(openssl rand -hex 32),TYPEDMEM_DB=/data/agent.db \
  --args="--profile,personal,serve,--identity-audience,https://typedmem-xxxxxx-uc.a.run.app" \
  --no-allow-unauthenticated
```

Note the `--args=` ordering: global flags (`--profile`) come before the `serve` subcommand; serve-specific flags (`--identity-audience`) come after. `TYPEDMEM_DB` env var picks the store path so no `--store` is needed in `--args=`.

Important constraints:

- **`--max-instances 1`** is required. SQLite-over-FUSE only handles a
  single writer; concurrent processes corrupt the database. If you need
  horizontal scale, use the Postgres backend (v0.7.x).
- **`--no-allow-unauthenticated`** + IAM-based access: callers (e.g. your
  ai-life-tracker service) need the `roles/run.invoker` role on the
  typedmem service, and pass a Google identity token in `Authorization`.

### 3. Call from another Cloud Run service

```python
# inside ai-life-tracker (Python example; TS pattern is the same)
import google.auth.transport.requests
import google.oauth2.id_token

target = "https://typedmem-xxxxxx-uc.a.run.app"
auth_req = google.auth.transport.requests.Request()
token = google.oauth2.id_token.fetch_id_token(auth_req, target)

import httpx
r = httpx.post(
    f"{target}/v1/memories",
    headers={"Authorization": f"Bearer {token}"},
    json={"memory": {"type": "observation", "content": "first steps today",
                     "subject": "milestone", "workspace": "user-abc123"},
          "event_source": "user", "event_source_name": "ai-life-tracker:entry"},
)
```

For Node/TypeScript callers, use the `google-auth-library` package (or
`@google-cloud/run` for service-to-service patterns).

## Deploy: Docker

```bash
docker run -d --name typedmem \
  -p 8080:8080 \
  -v /var/lib/typedmem:/data \
  -e TYPEDMEM_API_TOKEN=$(openssl rand -hex 32) \
  ghcr.io/canis-minor/typedmem:0.7.0 \
  --profile personal serve
```

The image's default `CMD` is `["serve"]` and `TYPEDMEM_DB=/data/agent.db` is preset, so the container runs `typedmem serve` against `/data/agent.db` out of the box. Override `TYPEDMEM_DB` or pass `--store /elsewhere/db.sqlite` *before* `serve` to point at a different file.

## Deploy: bare metal / VPS / systemd

```ini
# /etc/systemd/system/typedmem.service
[Unit]
Description=TypedMemory HTTP server
After=network.target

[Service]
Type=simple
User=typedmem
Environment=TYPEDMEM_API_TOKEN=<random>
Environment=TYPEDMEM_DB=/var/lib/typedmem/agent.db
ExecStart=/usr/local/bin/typedmem --profile personal serve --port 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Operational notes

- **`/healthz`** returns `{"status": "ok"}` always — wire it to your load
  balancer / Cloud Run readiness probe.
- **`/docs`** is auto-generated interactive API docs (Swagger UI).
- **CORS** is off by default. Add `--cors-origin '*'` or a specific origin
  if a browser app calls the server directly. Most production setups put
  typedmem behind a backend-for-frontend, so CORS isn't needed.
- **Logging** is whatever uvicorn does by default; control with
  `--log-level debug` etc.
- **Concurrency**: SQLite serializes writes. For high write volume, run
  one server instance and queue at the client, or wait for the Postgres
  backend in v0.7.x.

## What's NOT here yet

- Streaming change feeds (SSE / WebSocket on `changed_since`) — v0.7.x
- Per-user / per-workspace API tokens — v0.7.x
- Sentence-transformer embedder — v0.7.x
- Postgres backend for horizontal scale — v0.7.x
- gRPC — no plans

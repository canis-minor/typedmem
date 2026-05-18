"""Server configuration. Built once at startup, frozen after."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """Runtime knobs for the typedmem HTTP server.

    Auth model: if neither ``api_token`` nor ``identity_audience`` is set,
    the server is unauthenticated (local dev only). If both are set, either
    valid bearer token OR valid Google ID token is accepted — this is the
    documented Cloud-Run-plus-local-dev pattern.
    """

    # Bearer-token auth (set TYPEDMEM_API_TOKEN env or --api-token flag).
    # Compared with constant_time_compare against the Authorization header.
    api_token: str | None = None

    # Google identity-token auth (set --identity-audience on Cloud Run).
    # Usually the typedmem service URL itself, e.g.
    # "https://typedmem-xxxxxx-uc.a.run.app". google-auth validates the
    # incoming ID token's signature, expiry, and audience claim.
    identity_audience: str | None = None

    # CORS: pass "*" or a single origin (Cloud Run is typically server-to-
    # server; browsers usually don't talk to the server directly).
    cors_origin: str | None = None

    # Surfaced on /v1/version. Mostly cosmetic.
    instance_name: str = "typedmem"

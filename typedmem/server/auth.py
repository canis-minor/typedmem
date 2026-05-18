"""Auth: bearer token (dev) + Google identity token (Cloud Run prod).

A request passes if EITHER auth source accepts it. If the server has no
auth configured at all (both ``api_token`` and ``identity_audience`` are
None), every request passes — that's the documented local-dev mode.

The Google ID token path is opt-in: ``google-auth`` is imported lazily so
default installs don't need it. Cloud Run deployments install via
``pip install 'typedmem[gcp]'`` which pulls in ``google-auth``.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request

from .config import ServerConfig


def _check_bearer(token: str, expected: str) -> bool:
    """Constant-time compare so we don't leak token length via timing."""
    return hmac.compare_digest(token.encode(), expected.encode())


def _check_google_id_token(token: str, audience: str) -> bool:
    """Validate a Google-issued ID token's signature, expiry, and audience.

    Returns True iff the token verifies. Raises nothing — caller decides
    the auth disposition. Imports google-auth lazily so the dependency is
    only needed on Cloud Run deploys.
    """
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token as g_id_token
    except ImportError:
        return False
    try:
        g_id_token.verify_oauth2_token(token, g_requests.Request(), audience)
    except Exception:
        return False
    return True


def make_auth_dependency(config: ServerConfig):
    """Build a FastAPI dependency that enforces the configured auth model.

    Wired in app.py via Depends(...) on the protected router. ``/healthz``
    and ``/v1/version`` bypass auth so Cloud Run health checks and curl
    probes work without a token.
    """

    no_auth = config.api_token is None and config.identity_audience is None

    async def auth_dep(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        if no_auth:
            return  # local-dev mode; everything allowed
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail={"error": "missing Bearer token", "code": "unauthenticated"},
            )
        token = authorization[len("Bearer "):].strip()
        if config.api_token is not None and _check_bearer(token, config.api_token):
            return
        if config.identity_audience is not None and _check_google_id_token(
            token, config.identity_audience
        ):
            return
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid token", "code": "unauthenticated"},
        )

    return auth_dep

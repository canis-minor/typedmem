"""TypedMemory HTTP server (v0.7+).

Exposes the existing Python surface as REST under ``/v1/``. Optional extra:
``pip install 'typedmem[server]'``. Start with ``typedmem serve --store ...``.

The server is library-shaped: ``create_app(store, embedder, api_token=...,
identity_audience=...)`` returns a configured FastAPI app you can mount
inside a larger ASGI app, or just hand to uvicorn directly.
"""

from __future__ import annotations

try:
    from .app import create_app
    from .config import ServerConfig
except ImportError as exc:  # fastapi / pydantic not installed
    _IMPORT_ERROR = exc

    def create_app(*args, **kwargs):  # type: ignore[no-redef]
        raise ImportError(
            "typedmem.server requires the 'server' extra. "
            "Install with: pip install 'typedmem[server]'"
        ) from _IMPORT_ERROR

    ServerConfig = None  # type: ignore[assignment,misc]


__all__ = ["create_app", "ServerConfig"]

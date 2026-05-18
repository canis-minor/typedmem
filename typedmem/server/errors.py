"""Translate Python exceptions into structured HTTP errors.

The Python API throws ``ValueError`` for bad input, ``KeyError`` for
not-found, and profile-rejection raises ``ValueError`` too. The server
maps these to the right HTTP status + JSON body so clients can act on
``error_response.code`` without parsing message strings.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def _error_body(error: str, code: str, **details) -> dict:
    return {"error": error, "code": code, "details": details}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):
        msg = str(exc)
        # Profile validation rejections carry "profile ... rejected memory"
        if "rejected memory" in msg:
            return JSONResponse(
                status_code=422,
                content=_error_body(msg, "profile_validation_error"),
            )
        return JSONResponse(
            status_code=400,
            content=_error_body(msg, "validation_error"),
        )

    @app.exception_handler(KeyError)
    async def _key_error(request: Request, exc: KeyError):
        return JSONResponse(
            status_code=404,
            content=_error_body(str(exc.args[0] if exc.args else "not found"),
                                 "not_found"),
        )

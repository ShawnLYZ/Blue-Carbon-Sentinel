"""Error envelope (addendum I1), identical to the Ground Station's: ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("bcs_sim.api")

_HTTP_CODES = {
    404: "not_found",
    405: "method_not_allowed",
    429: "rate_limited",
    501: "not_implemented",
    503: "upstream_unavailable",
}


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


class ApiError(Exception):
    """Raised by a route: answered as the I1 envelope with ``status``."""

    def __init__(self, code: str, status: int, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code, self.status, self.message, self.details = code, status, message, details


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(envelope(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            envelope("validation_error", "Request validation failed.", jsonable_encoder({"errors": errors})),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = str(exc.detail) if exc.detail else code.replace("_", " ")
        return JSONResponse(envelope(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(envelope("internal_error", "Internal server error."), status_code=500)

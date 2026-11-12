"""Uniform error model.

Every error response has the shape::

    {"error": {"code": "ROOM_UNAVAILABLE", "message": "...", "params": {...},
               "fields": [{"loc": ["body", "number"], "code": "..."}]}}

`code` is stable and translated by clients (all five languages); `message` is
an English fallback for logs and API scripts.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("hms.errors")


class AppError(Exception):
    status_code = 400
    default_code = "BAD_REQUEST"

    def __init__(
        self,
        code: str | None = None,
        message: str = "",
        *,
        status_code: int | None = None,
        params: dict[str, Any] | None = None,
        fields: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code or self.default_code
        self.message = message or self.code
        if status_code is not None:
            self.status_code = status_code
        self.params = params or {}
        self.fields = fields or []
        super().__init__(self.message)


class NotFound(AppError):
    status_code = 404
    default_code = "NOT_FOUND"


class Conflict(AppError):
    status_code = 409
    default_code = "CONFLICT"


class Forbidden(AppError):
    status_code = 403
    default_code = "FORBIDDEN"


class Unauthorized(AppError):
    status_code = 401
    default_code = "UNAUTHORIZED"


class ValidationFailed(AppError):
    status_code = 422
    default_code = "VALIDATION_FAILED"


class VersionConflict(Conflict):
    default_code = "VERSION_CONFLICT"


def field_error(field: str, code: str, **ctx: Any) -> dict[str, Any]:
    return {"loc": ["body", field], "code": code, "ctx": ctx}


# Constraint name -> (error code, http status, field). Modules register the
# constraints whose violation is a user error rather than a bug.
_CONSTRAINT_ERRORS: dict[str, tuple[str, int, str | None]] = {}


def register_constraint(name: str, code: str, status: int = 409, field: str | None = None) -> None:
    _CONSTRAINT_ERRORS[name] = (code, status, field)


def _pg_details(exc: IntegrityError) -> tuple[str | None, str | None]:
    orig = exc.orig
    candidates = [orig, getattr(orig, "__cause__", None)]
    sqlstate = constraint = None
    for c in candidates:
        if c is None:
            continue
        sqlstate = sqlstate or getattr(c, "sqlstate", None) or getattr(c, "pgcode", None)
        constraint = constraint or getattr(c, "constraint_name", None)
    return sqlstate, constraint


def integrity_to_app_error(exc: IntegrityError) -> AppError:
    sqlstate, constraint = _pg_details(exc)
    if constraint and constraint in _CONSTRAINT_ERRORS:
        code, status, field = _CONSTRAINT_ERRORS[constraint]
        fields = [field_error(field, code)] if field else []
        return AppError(code, code, status_code=status, fields=fields)
    if sqlstate == "23503":  # foreign_key_violation
        # Deleting something still referenced, or referencing something missing.
        return Conflict("IN_USE_OR_MISSING_REFERENCE", "Referenced record is in use or missing")
    if sqlstate == "23P01":  # exclusion_violation (room allocation ledger)
        return Conflict("ROOM_UNAVAILABLE", "Room is already allocated for these dates")
    if sqlstate == "23505":
        return Conflict("DUPLICATE", "A record with these values already exists")
    log.exception("Unmapped integrity error", exc_info=exc)
    return Conflict("INTEGRITY_ERROR", "Database integrity error")


def _body(code: str, message: str, params: dict | None = None, fields: list | None = None) -> dict:
    return {"error": {"code": code, "message": message, "params": params or {}, "fields": fields or []}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.params, exc.fields), status_code=exc.status_code)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        err = integrity_to_app_error(exc)
        return JSONResponse(_body(err.code, err.message, err.params, err.fields), err.status_code)

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, exc: StaleDataError) -> JSONResponse:
        return JSONResponse(_body("VERSION_CONFLICT", "Record was modified by someone else"), status_code=409)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for e in exc.errors():
            ctx = {k: v for k, v in (e.get("ctx") or {}).items() if isinstance(v, str | int | float)}
            fields.append({"loc": list(e.get("loc", [])), "code": e.get("type"), "ctx": ctx})
        return JSONResponse(
            _body("VALIDATION_FAILED", "Request validation failed", fields=fields),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse(_body("INTERNAL_ERROR", "Internal server error"), status_code=500)

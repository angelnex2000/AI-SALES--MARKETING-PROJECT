"""Phase 5 Module 11 — one error shape for the whole API.

Business code raises an `AppError` subclass; three registered handlers
serialise `AppError`, raw `HTTPException`, and Pydantic
`RequestValidationError` into the uniform envelope
`{success, message, error_code, details}`. Registered in app/main.py via
`register_exception_handlers(app)`.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base for all domain errors. Raise a subclass from services/routers
    instead of building JSON responses by hand."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code
        super().__init__(message)


class NotFoundError(AppError):
    """Use for cross-tenant / unassigned access too — a 404 (not 403) so the
    API never confirms a resource the caller shouldn't know exists."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class DuplicateError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "DUPLICATE"


class ForbiddenError(AppError):
    """Reserve for 'your role categorically cannot do this action' — not for
    isolation (that is NotFoundError)."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"


# Map bare HTTPException status codes to stable error_code strings so even
# handlers that raise HTTPException produce a consistent envelope.
_STATUS_TO_CODE = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "VALIDATION_ERROR",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMIT_EXCEEDED",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "SERVER_ERROR",
}


def _envelope(status_code: int, message: str, error_code: str, details: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "message": message,
            "error_code": error_code,
            "details": jsonable_encoder(details) if details else {},
        },
    )


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return _envelope(exc.status_code, exc.message, exc.error_code, exc.details)


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    error_code = _STATUS_TO_CODE.get(exc.status_code, "ERROR")
    return _envelope(exc.status_code, str(exc.detail), error_code)


async def _validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default 422 body is not our envelope — override it here.
    return _envelope(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Request validation failed",
        "VALIDATION_ERROR",
        details={"errors": exc.errors()},
    )


async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Anything we did not anticipate. The traceback goes to the logs (with
    its request id attached); the client gets a generic message, because
    exception text routinely leaks table names, SQL, and provider keys."""
    logging.getLogger("app.error").exception("unhandled exception", exc_info=exc)
    return _envelope(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An unexpected error occurred",
        "SERVER_ERROR",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    # Registered last and deliberately broadest — without it an unhandled
    # error escapes as Starlette's plain-text 500, breaking the envelope
    # contract the frontend's axios interceptor relies on.
    app.add_exception_handler(Exception, _unhandled_exception_handler)

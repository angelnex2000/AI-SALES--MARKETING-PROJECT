"""Phase 7 Module 3 — structured application logging.

Logs go to **stdout only**. There is deliberately no `system_logs` table:
generic app logging belongs in an external aggregator, and only queryable
business records (`audit_logs`, `ai_interaction_logs`) earn a table. Do not
add a DB sink here.

Two pieces:
  * `configure_logging()` — installs one stdout handler on the root logger,
    JSON in production, human-readable in development.
  * `RequestLoggingMiddleware` — assigns each request an id, exposes it via
    a ContextVar so every log line emitted while handling that request
    carries it, and returns it as the `X-Request-ID` response header.

Nothing here logs request bodies, headers, or query strings: those routinely
carry credentials, lead PII, and OAuth tokens. Only method, path, status,
and duration.
"""

import json
import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

# "-" when a log line is emitted outside any request (startup, Celery worker).
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes present on every LogRecord; anything else a caller passed via
# `extra=` is application context worth serialising into the JSON payload.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"asctime", "message", "request_id", "taskName"}


class RequestIdFilter(logging.Filter):
    """Stamps the current request id onto every record, so the formatter can
    rely on the attribute existing even for third-party loggers."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line — the shape log aggregators expect."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable single line for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def configure_logging() -> None:
    """Idempotent — safe to call from both the API lifespan and the Celery
    worker, which start separate processes but share this module."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if settings.resolved_log_format == "json" else ConsoleFormatter()
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())

    # uvicorn installs its own handlers; drop them so output isn't duplicated
    # in two different formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # uvicorn.access already logs every request and we do it ourselves with
    # richer fields — leaving both on doubles every line.
    logging.getLogger("uvicorn.access").disabled = True


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs one line per completed request, with a correlation id.

    An inbound `X-Request-ID` is honoured so a trace started at the frontend
    or a load balancer survives into these logs; otherwise we mint one.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_ctx.set(request_id)
        # Also on request.state so routers/services can read it without
        # importing the ContextVar.
        request.state.request_id = request_id

        logger = logging.getLogger("app.request")
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # No exc_info here: the traceback is logged once, by the 500
            # handler in core/exceptions.py. This line only adds the timing
            # and path context that handler cannot see.
            logger.error(
                "request failed",
                extra={
                    "http_method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            # Deliberately NOT resetting the ContextVar before re-raising:
            # the 500 handler runs further out in the stack (Starlette's
            # ServerErrorMiddleware wraps user middleware), and resetting
            # here would strip the request id off the traceback it logs.
            # Each request gets its own context, so nothing leaks between them.
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        # 5xx is our bug, 4xx is usually the caller's — don't page on the latter.
        level = logging.ERROR if response.status_code >= 500 else logging.INFO
        logger.log(
            level,
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        request_id_ctx.reset(token)
        return response

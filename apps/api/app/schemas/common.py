"""Phase 5 — the single response envelope every endpoint returns.

`{success, message, data}` on success and `{success, message, error_code,
details}` on error (produced by app/core/exceptions.py). Kept as a generic
Pydantic model so FastAPI's OpenAPI schema stays accurate per-endpoint.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str | None = None
    data: T | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    error_code: str
    details: dict[str, Any] = {}


def ok(data: Any = None, message: str | None = None) -> dict[str, Any]:
    """Convenience for routers that return plain dicts rather than a typed
    ApiResponse[Model]."""

    return {"success": True, "message": message, "data": data}

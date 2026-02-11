"""
Standardized error responses for the Pricing API.

Contract:
    Every error response MUST have this shape:
    {
        "error": {
            "code": "MACHINE_READABLE_CODE",
            "message": "Human-readable description"
        }
    }

Usage in endpoints:
    from app.core.exceptions import api_error, ErrorCode

    raise api_error(404, ErrorCode.NOT_FOUND, "Producto no encontrado")

The global exception handler in main.py ensures this shape even for
unhandled errors and FastAPI validation errors.
"""

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Error codes — machine-readable, stable contract for frontend/integrations
# ---------------------------------------------------------------------------


class ErrorCode:
    """Centralized error codes. Add new ones here, never inline magic strings."""

    # Auth (1xx prefix conceptually)
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INACTIVE_USER = "INACTIVE_USER"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_TOKEN_TYPE = "INVALID_TOKEN_TYPE"
    MISSING_TOKEN = "MISSING_TOKEN"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"

    # Resources (4xx)
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # Business logic
    MISSING_CONFIGURATION = "MISSING_CONFIGURATION"
    CALCULATION_ERROR = "CALCULATION_ERROR"

    # Server
    INTERNAL_ERROR = "INTERNAL_ERROR"
    REGISTRATION_DISABLED = "REGISTRATION_DISABLED"


# ---------------------------------------------------------------------------
# Response model — used in OpenAPI docs
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Standard error envelope. All API errors follow this shape."""

    error: ErrorDetail

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Producto no encontrado",
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# Helper to raise consistent errors
# ---------------------------------------------------------------------------


def api_error(
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    """
    Create an HTTPException with the standard error payload.

    Returns the exception (caller must `raise` it).
    """
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


# ---------------------------------------------------------------------------
# Global exception handler — register in main.py
# ---------------------------------------------------------------------------


def http_exception_handler(_request, exc: HTTPException) -> JSONResponse:
    """
    Normalize all HTTPException responses to the standard error shape.

    If detail is already a dict with 'code', pass through.
    If detail is a plain string (legacy), wrap it with a generic code.
    """
    detail = exc.detail

    if isinstance(detail, dict) and "code" in detail:
        body = {"error": detail}
    else:
        # Legacy: plain string detail — wrap with status-based code
        code = _status_to_code(exc.status_code)
        message = detail if isinstance(detail, str) else str(detail)
        body = {"error": {"code": code, "message": message}}

    return JSONResponse(status_code=exc.status_code, content=body)


def _status_to_code(status_code: int) -> str:
    """Map HTTP status to a default error code for legacy exceptions."""
    mapping = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.INVALID_TOKEN,
        403: ErrorCode.INSUFFICIENT_PERMISSIONS,
        404: ErrorCode.NOT_FOUND,
        409: ErrorCode.ALREADY_EXISTS,
        422: ErrorCode.VALIDATION_ERROR,
    }
    return mapping.get(status_code, ErrorCode.INTERNAL_ERROR)

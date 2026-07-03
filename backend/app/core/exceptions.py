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
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


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
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"


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


def http_exception_handler(_request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Normalize all HTTPException responses to the standard error shape.

    Policy (revisado en COMPRAS-7.2):
      1. Si `detail` es un dict con `code` (convención inglés del envelope
         estándar) → lo envolvemos en `{"error": detail}` manteniendo
         backward-compat con el resto de la API.
      2. Si `detail` es un dict con `codigo` (convención castellano usada por
         el módulo de compras para payloads estructurados — 409
         POSIBLE_DUPLICADO_OP_ERP, 422 OP_CAJA_MONEDA_MISMATCH, etc.) o
         cualquier otro dict → se preserva el dict tal cual COMO RAÍZ del
         body (no lo envolvemos en `error` para no romper el contrato del
         frontend que lee `response.data.codigo` / `response.data.duplicados_detectados`).
      3. Si `detail` es un string (legacy) → lo envolvemos en el envelope
         con un código derivado del status.

    Esto garantiza que los payloads estructurados (cualquier clave del dict
    original) lleguen intactos al cliente.
    """
    detail = exc.detail

    if isinstance(detail, dict):
        if "code" in detail:
            # Envelope estándar inglés — comportamiento previo preservado.
            body: dict = {"error": detail}
        else:
            # Dict con estructura propia (p. ej. `codigo`/`mensaje`/`duplicados_detectados`
            # del módulo compras). Se retorna tal cual para preservar el contrato.
            body = detail
    else:
        # Legacy: plain string detail — wrap with status-based code.
        code = _status_to_code(exc.status_code)
        message = detail if isinstance(detail, str) else str(detail)
        body = {"error": {"code": code, "message": message}}

    # `jsonable_encoder` serializa datetime/Decimal/Enum/UUID correctamente
    # cuando el dict lleva tipos no-JSON nativos (ej: duplicados del ERP con
    # ct_date: datetime y ct_total: Decimal). Antes el fallback `str(detail)`
    # tapaba el problema — ahora que preservamos el dict, hay que codificarlo.
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(body),
        headers=getattr(exc, "headers", None),
    )


def _status_to_code(status_code: int) -> str:
    """Map HTTP status to a default error code for legacy exceptions."""
    mapping = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.INVALID_TOKEN,
        403: ErrorCode.INSUFFICIENT_PERMISSIONS,
        404: ErrorCode.NOT_FOUND,
        405: ErrorCode.METHOD_NOT_ALLOWED,
        409: ErrorCode.ALREADY_EXISTS,
        422: ErrorCode.VALIDATION_ERROR,
    }
    return mapping.get(status_code, ErrorCode.INTERNAL_ERROR)

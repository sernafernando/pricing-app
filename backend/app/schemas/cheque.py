"""
Schemas Pydantic v2 — Módulo de Cheques.

Cubre: Chequera (create/response), Cheque (create propio, anular, response),
ChequeEvento (response), respuestas de listado.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ──────────────────────────────────────────────────────────────────────────
# Chequera
# ──────────────────────────────────────────────────────────────────────────


class ChequeraCreate(BaseModel):
    """Payload para crear una chequera."""

    banco_empresa_id: int
    descripcion: Optional[str] = None
    instrumento: str = Field(default="fisico", pattern="^(fisico|echeq)$")
    numero_desde: Optional[int] = Field(default=None, ge=0)
    numero_hasta: Optional[int] = Field(default=None, ge=0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "banco_empresa_id": 1,
                "descripcion": "Talonario principal",
                "instrumento": "fisico",
                "numero_desde": 1,
                "numero_hasta": 100,
            }
        }
    )


class ChequeraResponse(BaseModel):
    """Respuesta de chequera."""

    id: int
    banco_empresa_id: int
    descripcion: Optional[str]
    instrumento: str
    numero_desde: Optional[int]
    numero_hasta: Optional[int]
    proximo_numero: Optional[int]
    activa: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────────────────────────────────
# Cheque
# ──────────────────────────────────────────────────────────────────────────


class EmitirChequePropio(BaseModel):
    """Payload para emitir un cheque propio (standalone)."""

    banco_empresa_id: int
    chequera_id: Optional[int] = None
    instrumento: str = Field(default="fisico", pattern="^(fisico|echeq)$")
    numero: str = Field(min_length=1, max_length=40)
    monto: Decimal = Field(gt=0)
    moneda: str = Field(default="ARS", pattern="^(ARS|USD)$")
    fecha_emision: date
    fecha_pago: date
    proveedor_id: Optional[int] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "banco_empresa_id": 1,
                "chequera_id": 1,
                "numero": "00000001",
                "monto": "1000.00",
                "moneda": "ARS",
                "fecha_emision": "2026-06-19",
                "fecha_pago": "2026-06-19",
            }
        }
    )


class AnularChequeRequest(BaseModel):
    """Payload para anular un cheque."""

    motivo: str = Field(min_length=1, max_length=500)

    model_config = ConfigDict(json_schema_extra={"example": {"motivo": "Error de emisión"}})


class ChequeEventoResponse(BaseModel):
    """Respuesta de un evento de cheque."""

    id: int
    tipo: str
    payload: Optional[Any]
    usuario_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChequeResponse(BaseModel):
    """Respuesta completa de un cheque (con o sin eventos)."""

    id: int
    tipo: str
    instrumento: str
    estado: str
    numero: str
    monto: Decimal
    moneda: str
    fecha_emision: date
    fecha_pago: date
    es_diferido: bool
    banco_empresa_id: Optional[int]
    chequera_id: Optional[int]
    proveedor_id: Optional[int]
    orden_pago_id: Optional[int]
    motivo_anulacion: Optional[str]
    created_at: datetime
    eventos: list[ChequeEventoResponse] = []
    banco_nombre: Optional[str] = None
    proveedor_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ChequeListResponse(BaseModel):
    """Respuesta de cheque para listados (sin eventos — evita N+1)."""

    id: int
    tipo: str
    instrumento: str
    estado: str
    numero: str
    monto: Decimal
    moneda: str
    fecha_emision: date
    fecha_pago: date
    es_diferido: bool
    banco_empresa_id: Optional[int]
    chequera_id: Optional[int]
    proveedor_id: Optional[int]
    orden_pago_id: Optional[int]
    motivo_anulacion: Optional[str]
    created_at: datetime
    banco_nombre: Optional[str] = None
    proveedor_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ChequePaginated(BaseModel):
    """Respuesta paginada del listado de cheques."""

    items: list[ChequeListResponse]
    total: int
    page: int
    page_size: int


class ChequeraPaginated(BaseModel):
    """Respuesta paginada del listado de chequeras."""

    items: list[ChequeraResponse]
    total: int
    page: int
    page_size: int

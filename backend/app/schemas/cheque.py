"""
Schemas Pydantic v2 — Módulo de Cheques.

Cubre: Chequera (create/response), Cheque (create propio, anular, response),
ChequeEvento (response), respuestas de listado.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    banco_deposito_id: Optional[int] = None
    proveedor_id: Optional[int]
    orden_pago_id: Optional[int]
    motivo_anulacion: Optional[str]
    created_at: datetime
    eventos: list[ChequeEventoResponse] = []
    banco_nombre: Optional[str] = None
    proveedor_nombre: Optional[str] = None
    cuit_librador: Optional[str] = None
    librador_nombre: Optional[str] = None

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
    banco_deposito_id: Optional[int] = None
    proveedor_id: Optional[int]
    orden_pago_id: Optional[int]
    motivo_anulacion: Optional[str]
    created_at: datetime
    banco_nombre: Optional[str] = None
    proveedor_nombre: Optional[str] = None
    cuit_librador: Optional[str] = None
    librador_nombre: Optional[str] = None

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


# ──────────────────────────────────────────────────────────────────────────
# Slice 2 — Cheques de terceros
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# Slice 3 — e-cheq transiciones manuales
# ──────────────────────────────────────────────────────────────────────────


class TransicionEcheqRequest(BaseModel):
    """Payload para transiciones manuales de e-cheq.

    accion: 'aceptar' | 'rechazar_emision' | 'poner_en_custodia'
    motivo: requerido para rechazar_emision; opcional para las demás acciones.
    """

    accion: str = Field(pattern=r"^(aceptar|rechazar_emision|poner_en_custodia)$")
    motivo: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _motivo_requerido_para_rechazar(self) -> "TransicionEcheqRequest":
        if self.accion == "rechazar_emision" and not (self.motivo and self.motivo.strip()):
            raise ValueError("motivo es requerido cuando accion='rechazar_emision'")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "accion": "rechazar_emision",
                "motivo": "Rechazo bancario por fondos insuficientes",
            }
        }
    )


# ──────────────────────────────────────────────────────────────────────────
# Slice 4 — Conciliación bancaria
# ──────────────────────────────────────────────────────────────────────────


class DebitarChequeRequest(BaseModel):
    """Payload para debitar un cheque propio (emitido|diferido → debitado).

    fecha: fecha real del débito (por defecto hoy en el endpoint; no antes de fecha_pago).
    """

    fecha: Optional[date] = None

    model_config = ConfigDict(json_schema_extra={"example": {"fecha": "2026-06-22"}})


class DepositarChequeRequest(BaseModel):
    """Payload para depositar un cheque de tercero en una cuenta bancaria de la empresa.

    banco_empresa_id: cuenta destino del depósito (moneda debe coincidir con el cheque).
    fecha: fecha del depósito (por defecto hoy; no antes de fecha_pago).
    """

    banco_empresa_id: int
    fecha: Optional[date] = None

    model_config = ConfigDict(json_schema_extra={"example": {"banco_empresa_id": 2, "fecha": "2026-06-22"}})


class AcreditarChequeRequest(BaseModel):
    """Payload para acreditar un cheque (depositado|en_custodia → acreditado).

    fecha: fecha real de la acreditación (por defecto hoy).
    """

    fecha: Optional[date] = None

    model_config = ConfigDict(json_schema_extra={"example": {"fecha": "2026-06-22"}})


class ChequeReporteResponse(BaseModel):
    """Respuesta del reporte FR-4.4 — cheques agrupados por segmento."""

    en_cartera: list[ChequeListResponse]
    a_debitar: list[ChequeListResponse]
    vencidos: list[ChequeListResponse]


class RecibirChequeTercero(BaseModel):
    """Payload para dar de alta un cheque de tercero a la cartera.

    El cheque se crea en estado `en_cartera` y NO requiere chequera ni
    banco_empresa propio.  Los campos banco_nombre y cuit_librador son
    obligatorios porque identifican al librador externo del cheque.
    """

    banco_nombre: str = Field(min_length=1, max_length=120)
    cuit_librador: str = Field(min_length=11, max_length=13, pattern=r"^\d{2}-?\d{8}-?\d{1}$")
    librador_nombre: Optional[str] = Field(default=None, max_length=160)
    numero: str = Field(min_length=1, max_length=40)
    monto: Decimal = Field(gt=0)
    moneda: str = Field(default="ARS", pattern="^(ARS|USD)$")
    fecha_emision: date
    fecha_pago: date
    instrumento: str = Field(default="fisico", pattern="^(fisico|echeq)$")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "banco_nombre": "Banco Galicia",
                "cuit_librador": "20304050607",
                "librador_nombre": "Empresa ABC SRL",
                "numero": "000000123456",
                "monto": "50000.00",
                "moneda": "ARS",
                "fecha_emision": "2026-06-22",
                "fecha_pago": "2026-07-22",
                "instrumento": "fisico",
            }
        }
    )

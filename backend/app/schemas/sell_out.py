"""Schemas of the sell-out campaigns API (`/api/sell-out/campanas`).

Only the shape is validated here (types and closed choices), like the sell-in
schemas. The rules that mirror the database CHECKs (amount by type, percentage
range, dates, FX rate, caps, at least one existing group) live in
`app.services.sell_out.campanas.validar`, so they come back as a 422 with one
readable Spanish message.

Numbers are bounded to their column types (`app.models.sell_out`), so a value
the database cannot hold is a 422 here instead of an error at commit. A value
with more decimals than its column keeps is rejected, not rounded: these are
amounts the brand owes, and a silent rounding would store a different amount
than the operator typed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Tipo = Literal["por_unidad", "porcentaje"]
BasePorcentaje = Literal["costo", "precio_neto"]
Moneda = Literal["ARS", "USD"]
TcModo = Literal["al_cobro", "fijo", "dia_venta"]
Estado = Literal["activa", "anulada"]

NOMBRE_MAX = 200
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)
GRUPOS_MAX = 50
INT_MIN, INT_MAX = -(2**31), 2**31 - 1  # INTEGER

# Each NUMERIC(precision, scale) column as (max_digits, decimal_places).
MONTO = {"max_digits": 18, "decimal_places": 2}  # monto_unit, tope_monto: NUMERIC(18, 2)
PORCENTAJE = {"max_digits": 7, "decimal_places": 4}  # NUMERIC(7, 4)
TIPO_CAMBIO = {"max_digits": 18, "decimal_places": 6}  # NUMERIC(18, 6)


class SellOutCampanaIn(BaseModel):
    """Create, and full replace on edit."""

    nombre: str = Field(max_length=NOMBRE_MAX)
    descripcion: Optional[str] = None
    fecha_desde: date
    fecha_hasta: date  # inclusive
    tipo: Tipo
    monto_unit: Optional[Decimal] = Field(default=None, **MONTO)  # per unit, in `moneda`; only for `por_unidad`
    porcentaje: Optional[Decimal] = Field(default=None, **PORCENTAJE)  # only for `porcentaje`
    base_porcentaje: BasePorcentaje = "costo"
    moneda: Moneda = "USD"
    # USD only; None means `al_cobro`. ARS campaigns send neither field.
    tc_modo: Optional[TcModo] = None
    # ARS per USD: required for `fijo`, never sent otherwise
    tipo_cambio: Optional[Decimal] = Field(default=None, **TIPO_CAMBIO)
    # cap shared by every product of the campaign
    tope_unidades: Optional[int] = Field(default=None, ge=INT_MIN, le=INT_MAX)
    tope_monto: Optional[Decimal] = Field(default=None, **MONTO)  # same, in `moneda`
    acumulable: bool = True
    # Whether `monto_unit` includes VAT: each sale then gets it net of its product's own VAT.
    monto_incluye_iva: bool = False
    grupo_ids: list[int] = Field(default_factory=list, max_length=GRUPOS_MAX)


class SellOutAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class SellOutTipoCambioIn(BaseModel):
    tipo_cambio: Decimal = Field(**TIPO_CAMBIO)  # ARS per USD, the rate the brand paid at


class SellOutGrupoOut(BaseModel):
    id: int
    nombre: str


class SellOutCampanaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    descripcion: Optional[str]
    fecha_desde: date
    fecha_hasta: date
    tipo: Tipo
    monto_unit: Optional[Decimal]
    porcentaje: Optional[Decimal]
    base_porcentaje: BasePorcentaje
    moneda: Moneda
    tc_modo: Optional[TcModo]
    tipo_cambio: Optional[Decimal]
    tc_definido_en: Optional[datetime]  # when an `al_cobro` rate was set
    tope_unidades: Optional[int]
    tope_monto: Optional[Decimal]
    acumulable: bool
    monto_incluye_iva: bool
    estado: Estado
    usuario_id: int
    created_at: datetime
    updated_at: datetime
    grupos: list[SellOutGrupoOut]


class SellOutCampanaListOut(BaseModel):
    items: list[SellOutCampanaOut]
    total: int
    page: int
    page_size: int

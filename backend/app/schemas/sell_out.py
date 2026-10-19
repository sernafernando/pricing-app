"""Schemas of the sell-out campaigns API (`/api/sell-out/campanas`).

Only the shape is validated here (types and closed choices), like the sell-in
schemas. The rules that mirror the database CHECKs (amount by type, percentage
range, dates, FX rate, caps, at least one existing group) live in
`app.services.sell_out.campanas.validar`, so they come back as a 422 with one
readable Spanish message.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Tipo = Literal["por_unidad", "porcentaje"]
BasePorcentaje = Literal["costo", "precio_neto"]
Moneda = Literal["ARS", "USD"]
Estado = Literal["activa", "anulada"]

NOMBRE_MAX = 200
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)
GRUPOS_MAX = 50


class SellOutCampanaIn(BaseModel):
    """Create, and full replace on edit."""

    nombre: str = Field(max_length=NOMBRE_MAX)
    descripcion: Optional[str] = None
    fecha_desde: date
    fecha_hasta: date  # inclusive
    tipo: Tipo
    monto_unit: Optional[Decimal] = None  # per unit, in `moneda`; only for `por_unidad`
    porcentaje: Optional[Decimal] = None  # only for `porcentaje`
    base_porcentaje: BasePorcentaje = "costo"
    moneda: Moneda = "ARS"
    tipo_cambio: Optional[Decimal] = None  # ARS per USD, fixed for the campaign; required in USD
    tope_unidades: Optional[int] = None  # cap shared by every product of the campaign
    tope_monto: Optional[Decimal] = None  # same, in `moneda`
    acumulable: bool = True
    grupo_ids: list[int] = Field(default_factory=list, max_length=GRUPOS_MAX)


class SellOutAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


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
    tipo_cambio: Optional[Decimal]
    tope_unidades: Optional[int]
    tope_monto: Optional[Decimal]
    acumulable: bool
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

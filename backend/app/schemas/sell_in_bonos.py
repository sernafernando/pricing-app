"""Schemas of the brand bonus API (`/api/sell-in/bonos`), sell-in-sell-out T3c-3.

Only the shape is validated here; the rules (the brand has products, a positive
amount, the date range) live in `app.services.sell_in.bonos_crud.validar`, so
they come back as a 422 with one readable Spanish message. `monto_unit` is
bounded to its column (NUMERIC(18, 2)): more decimals are rejected, never
rounded, since it is an amount the brand owes per unit.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Moneda = Literal["ARS", "USD"]
Estado = Literal["activa", "anulada"]

MARCA_MAX = 100  # productos_erp.marca is VARCHAR(100)
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)


class SellInBonoIn(BaseModel):
    """Create, and full replace on edit."""

    marca: str = Field(max_length=MARCA_MAX)
    monto_unit: Decimal = Field(max_digits=18, decimal_places=2)  # per invoiced unit, in `moneda`
    moneda: Moneda
    fecha_desde: date  # supplier invoice date, inclusive
    fecha_hasta: date  # inclusive
    descripcion: Optional[str] = None


class SellInBonoAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class SellInBonoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    marca: str
    monto_unit: Decimal
    moneda: Moneda
    fecha_desde: date
    fecha_hasta: date
    descripcion: Optional[str]
    estado: Estado
    usuario_id: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    # What the worker generated from it so far: active purchases, their units and amount (in `moneda`).
    compras_activas: int
    unidades: int
    monto_generado: Decimal


class SellInBonoListOut(BaseModel):
    items: list[SellInBonoOut]
    total: int
    page: int
    page_size: int

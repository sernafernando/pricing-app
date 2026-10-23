"""Schemas of the bonus API (`/api/sell-in/bonos`), sell-in-sell-out T3c-3 (scopes and % in T3e-3).

Only the shape is validated here; the rules (each scope carries its own field
and it reaches something, a positive amount or a percentage in (0, 100], the
date range) live in `app.services.sell_in.bonos_crud.validar`, so they come
back as a 422 with one readable Spanish message. `monto_unit` and `porcentaje`
are bounded to their columns (NUMERIC(18, 2) and NUMERIC(7, 4)): more decimals
are rejected, never rounded. A body without `alcance`/`tipo` is a brand bonus
per unit, as before.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Moneda = Literal["ARS", "USD"]
Estado = Literal["activa", "anulada"]
Alcance = Literal["marca", "categoria", "modelos", "factura"]
TipoBono = Literal["por_unidad", "porcentaje"]

MARCA_MAX = 100  # productos_erp.marca is VARCHAR(100)
CATEGORIA_MAX = 100  # productos_erp.categoria is VARCHAR(100)
MODELOS_MAX = 500
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)


class SellInBonoMontoOut(BaseModel):
    moneda: Moneda
    monto: Decimal


class SellInBonoModeloOut(BaseModel):
    item_id: int
    codigo: Optional[str]  # None when the catalog no longer has the item
    descripcion: Optional[str]


class SellInBonoIn(BaseModel):
    """Create, and full replace on edit."""

    alcance: Alcance = "marca"
    marca: Optional[str] = Field(default=None, max_length=MARCA_MAX)
    categoria: Optional[str] = Field(default=None, max_length=CATEGORIA_MAX)
    modelos: list[int] = Field(default_factory=list, max_length=MODELOS_MAX)  # item ids
    pedido_id: Optional[int] = None  # the Compras operation of an invoice bonus
    tipo: TipoBono = "por_unidad"
    monto_unit: Optional[Decimal] = Field(default=None, max_digits=18, decimal_places=2)  # per unit, in `moneda`
    porcentaje: Optional[Decimal] = Field(default=None, max_digits=7, decimal_places=4)  # of the invoiced net
    moneda: Moneda
    fecha_desde: date  # supplier invoice date, inclusive
    fecha_hasta: date  # inclusive
    descripcion: Optional[str] = None


class SellInBonoAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class SellInBonoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alcance: Alcance
    marca: Optional[str]
    categoria: Optional[str]
    modelos: list[SellInBonoModeloOut]
    pedido_id: Optional[int]
    pedido_numero: Optional[str]
    tipo: TipoBono
    monto_unit: Optional[Decimal]
    porcentaje: Optional[Decimal]
    moneda: Moneda
    fecha_desde: date
    fecha_hasta: date
    descripcion: Optional[str]
    estado: Estado
    usuario_id: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    # What the worker generated from it so far: active purchases, their units and amount (in `moneda`;
    # `montos_generados` per currency, in case a purchase was left in another one).
    compras_activas: int
    unidades: int
    monto_generado: Decimal
    montos_generados: list[SellInBonoMontoOut]


class SellInBonoListOut(BaseModel):
    items: list[SellInBonoOut]
    total: int
    page: int
    page_size: int


ALCANCE_LIMITE = 20  # rows per group of the bonus panel (`GET /{id}/alcance`), by default
ALCANCE_LIMITE_MAX = 100


class SellInBonoAlcanzadaOut(BaseModel):
    """An active purchase the worker generated for the bonus."""

    compra_id: int
    pedido_id: Optional[int]
    numero: Optional[str]
    proveedor_nombre: Optional[str]
    numero_factura: Optional[str]
    fecha_factura: Optional[date]
    unidades: int
    monto: Decimal
    moneda: Moneda


class SellInBonoPedidoOut(BaseModel):
    """A Compras operation of the bonus's scope that the bonus does not reach (yet)."""

    pedido_id: int
    numero: str
    proveedor_nombre: Optional[str]
    numero_factura: Optional[str]
    fecha_factura: Optional[date]
    unidades: int  # pending: received units; out of range: invoiced units (only the scope's)


class SellInBonoAlcanzadasOut(BaseModel):
    total: int
    items: list[SellInBonoAlcanzadaOut]


class SellInBonoPedidosOut(BaseModel):
    total: int
    items: list[SellInBonoPedidoOut]


class SellInBonoAlcanceOut(BaseModel):
    limite: int
    alcanzadas: SellInBonoAlcanzadasOut
    pendientes: SellInBonoPedidosOut
    fuera_de_rango: SellInBonoPedidosOut

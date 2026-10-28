"""Schemas of the sell-out campaigns API (`/api/sell-out/campanas`).

Only the shape is validated here (types and closed choices), like the sell-in
schemas. The rules that mirror the database CHECKs (amount by type, percentage
range, dates, FX rate, caps, at least one existing group, per-product amounts) live in
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
Canal = Literal["ml", "fuera", "tn"]
EstadoRecalculo = Literal["al_dia", "en_cola", "recalculando", "fallida"]

NOMBRE_MAX = 200
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)
GRUPOS_MAX = 50
ITEMS_MAX = 500
INT_MIN, INT_MAX = -(2**31), 2**31 - 1  # INTEGER

# Each NUMERIC(precision, scale) column as (max_digits, decimal_places).
MONTO = {"max_digits": 18, "decimal_places": 2}  # monto_unit, tope_monto: NUMERIC(18, 2)
PORCENTAJE = {"max_digits": 7, "decimal_places": 4}  # NUMERIC(7, 4)
TIPO_CAMBIO = {"max_digits": 18, "decimal_places": 6}  # NUMERIC(18, 6)


class SellOutCampanaItemIn(BaseModel):
    """A product's own amount per unit in a `por_unidad` campaign (T22b: legacy grouped offsets), in `moneda`,
    loaded with VAT or not like `monto_unit`. It replaces `monto_unit` for that product only; the cap is shared."""

    item_id: int = Field(ge=INT_MIN, le=INT_MAX)
    monto_unit: Decimal = Field(**MONTO)


class SellOutCampanaItemOut(BaseModel):
    item_id: int
    monto_unit: Decimal


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
    # Products of the groups with their own amount (`por_unidad` only); the rest get `monto_unit`.
    items: list[SellOutCampanaItemIn] = Field(default_factory=list, max_length=ITEMS_MAX)


class SellOutAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class SellOutTipoCambioIn(BaseModel):
    tipo_cambio: Decimal = Field(**TIPO_CAMBIO)  # ARS per USD, the rate the brand paid at


class SellOutGrupoOut(BaseModel):
    id: int
    nombre: str


class SellOutCanalOut(BaseModel):
    canal: Canal
    lineas: int
    unidades: int
    monto: Decimal  # in the campaign currency


class SellOutRecalculoOut(BaseModel):
    """The rebuild state from the `sell_out_dirty` queue (`app.services.sell_out.resumen`)."""

    estado: EstadoRecalculo
    intentos: int
    error: Optional[str]  # the last failure, while it has not been rebuilt since
    detenida: bool  # parked after too many failures: retried only when something queues it again
    encolada_en: Optional[datetime]


class SellOutResumenOut(BaseModel):
    """What the campaign credited so far (`app.services.sell_out.resumen`)."""

    lineas: int
    unidades: int
    monto: Decimal  # in the campaign currency
    monto_ars: Optional[Decimal]  # None when a USD row has no rate
    ars_estimado: bool  # `al_cobro` without its rate: the ARS amount is an estimate at the latest BNA
    tope_unidades_restantes: Optional[int]  # None without a unit cap
    tope_monto_restante: Optional[Decimal]  # None without a money cap
    por_canal: list[SellOutCanalOut]
    pendientes_base: int  # percentage sales skipped while their base is unknown
    recalculo: SellOutRecalculoOut


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
    offset_origen_id: Optional[int] = None  # read-only: the legacy offset it was migrated from (T15)
    created_at: datetime
    updated_at: datetime
    grupos: list[SellOutGrupoOut]
    items: list[SellOutCampanaItemOut] = []  # the products with their own amount, by item_id
    resumen: SellOutResumenOut


class SellOutCampanaListOut(BaseModel):
    items: list[SellOutCampanaOut]
    total: int
    page: int
    page_size: int


class SellOutConsumoOut(BaseModel):
    """One credited sale line. A return inside the campaign is netted into its sale's row."""

    id: int
    canal: Canal
    venta_ref: int  # ML `item_row_id`; fuera / TN `it_transaction`
    fecha_venta: date
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    unidades: int
    monto: Decimal  # in the campaign currency
    tc_venta: Optional[Decimal]  # ARS per USD the row converts at; None for ARS
    monto_ars: Optional[Decimal]


class SellOutConsumosListOut(BaseModel):
    moneda: Moneda
    ars_estimado: bool
    items: list[SellOutConsumoOut]
    total: int
    page: int
    page_size: int

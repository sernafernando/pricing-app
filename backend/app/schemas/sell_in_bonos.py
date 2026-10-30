"""Schemas of the bonus API (`/api/sell-in/bonos`), sell-in-sell-out T3c-3 (scopes and % in T3e-3).

Only the shape is validated here; the rules (each scope carries its own field
and it reaches something, a positive amount or a percentage in (0, 100], the
date range) live in `app.services.sell_in.bonos_crud.validar`, so they come
back as a 422 with one readable Spanish message. `monto_unit` and `porcentaje`
are bounded to their columns (NUMERIC(18, 2) and NUMERIC(7, 4)): more decimals
are rejected, never rounded. A body without `alcance`/`tipo` is a brand bonus
per unit, as before.

`modelos` takes item ids (as before) or objects `{item_id, monto_unit?,
porcentaje?}` (T23a): a model's own value of the bonus's kind replaces the
bonus's for it, bounded like the bonus's own field. A bare id on an edit keeps
the value the model had stored; an object's values are what is stored.

`tope_unidades` and `tope_monto` (T24) are the bonus's one cap shared by every
product and operation it reaches, in invoiced units and in its own currency
(`tope_monto` bounded like `monto_unit`). On an edit, a cap field left out of
the body keeps what was stored and an explicit null removes it, so a client that
does not know about caps never drops one. The response adds what is left of
each cap (never below zero; None without that cap).

`base` (T25d) is 'factura' (invoiced purchases, by invoice date) or
'costo_venta' (a % of the cost recorded on each sale, by sale date, ARS, no
purchase); it is set on create and never changes. `incluye_iva` (S33) only
exists on a cost bonus; left out on an edit, the stored one stays.
`offset_origen_id` is read-only (set by the offsets migration script).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Moneda = Literal["ARS", "USD"]
Estado = Literal["activa", "anulada"]
Alcance = Literal["marca", "categoria", "modelos", "factura"]
TipoBono = Literal["por_unidad", "porcentaje"]
BaseBono = Literal["factura", "costo_venta"]
# The one spelling of each base, shared by the services (T25d).
BASE_FACTURA, BASE_COSTO_VENTA = get_args(BaseBono)

MARCA_MAX = 100  # productos_erp.marca is VARCHAR(100)
CATEGORIA_MAX = 100  # productos_erp.categoria is VARCHAR(100)
MODELOS_MAX = 500
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)


class SellInBonoMontoOut(BaseModel):
    moneda: Moneda
    monto: Decimal


# A model's own value fits its `sell_in_bono_items` column: (field, label, max digits, decimal places).
_VALORES_MODELO = (("monto_unit", "El monto por unidad", 18, 2), ("porcentaje", "El porcentaje", 7, 4))


class SellInBonoModeloIn(BaseModel):
    """A model with its own value (T23a); neither: the bonus's. An unknown key is refused (`extra='forbid'`):
    a typo must not fall back to the bonus value silently."""

    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(ge=-(2**31), le=2**31 - 1)  # INTEGER, like a sell-out campaign's product
    monto_unit: Optional[Decimal] = None
    porcentaje: Optional[Decimal] = None

    @model_validator(mode="after")
    def _cabe_en_su_columna(self) -> "SellInBonoModeloIn":
        """Digits and decimals of each value, with a message naming the model."""
        for campo, etiqueta, digitos, decimales in _VALORES_MODELO:
            valor = getattr(self, campo)
            if valor is None or not valor.is_finite():
                continue
            exponente = valor.normalize().as_tuple().exponent
            if exponente < -decimales:
                raise ValueError(f"{etiqueta} del modelo {self.item_id} admite hasta {decimales} decimales")
            if len(valor.quantize(Decimal(1).scaleb(-decimales)).as_tuple().digits) > digitos:
                raise ValueError(f"{etiqueta} del modelo {self.item_id} tiene demasiados dígitos")
        return self


class SellInBonoModeloOut(BaseModel):
    item_id: int
    codigo: Optional[str]  # None when the catalog no longer has the item
    descripcion: Optional[str]
    monto_unit: Optional[Decimal] = None  # the model's own value; None: the bonus's
    porcentaje: Optional[Decimal] = None


class SellInBonoIn(BaseModel):
    """Create, and full replace on edit."""

    alcance: Alcance = "marca"
    marca: Optional[str] = Field(default=None, max_length=MARCA_MAX)
    categoria: Optional[str] = Field(default=None, max_length=CATEGORIA_MAX)
    # Item ids, or objects with a model's own value; a bare id on an edit keeps the stored value.
    modelos: list[Union[int, SellInBonoModeloIn]] = Field(default_factory=list, max_length=MODELOS_MAX)
    pedido_id: Optional[int] = None  # the Compras operation of an invoice bonus
    tipo: TipoBono = "por_unidad"
    monto_unit: Optional[Decimal] = Field(default=None, max_digits=18, decimal_places=2)  # per unit, in `moneda`
    porcentaje: Optional[Decimal] = Field(default=None, max_digits=7, decimal_places=4)  # of the invoiced net
    moneda: Moneda
    fecha_desde: date  # supplier invoice date, inclusive
    fecha_hasta: date  # inclusive
    descripcion: Optional[str] = None
    # One cap shared by everything the bonus reaches (T24); left out on an edit: the stored one stays.
    tope_unidades: Optional[int] = Field(default=None, le=2**31 - 1)  # invoiced units, INTEGER
    tope_monto: Optional[Decimal] = Field(default=None, max_digits=18, decimal_places=2)  # in `moneda`
    # T25d: set on create only; left out on an edit, the stored ones stay (`base` never changes).
    base: BaseBono = BASE_FACTURA
    incluye_iva: bool = False  # the loaded % includes VAT (S33); only on a 'costo_venta' bonus
    # T27b (S36): stacks with the other bonuses on the same product and dates (sell out's meaning); left out on an
    # edit, the stored one stays.
    acumulable: bool = True

    @field_validator("tope_unidades", mode="before")
    @classmethod
    def _unidades_no_booleano(cls, valor):
        """Lax mode would read `true` as 1 unit: a cap must be a number."""
        if isinstance(valor, bool):
            raise ValueError("El tope de unidades tiene que ser un número entero")
        return valor


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
    # The shared cap (T24) and what is left of it after `unidades` / `monto_generado`; None: no such cap.
    tope_unidades: Optional[int]
    tope_monto: Optional[Decimal]
    tope_unidades_restantes: Optional[int]
    tope_monto_restante: Optional[Decimal]
    # T25d: a 'costo_venta' bonus's `unidades` / `monto_generado` (ARS) are what its sales got
    # (`sell_in_bono_consumos`), and `compras_activas` is 0.
    base: BaseBono
    incluye_iva: bool
    acumulable: bool
    offset_origen_id: Optional[int]


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
    unidades: int  # pending: received units; out of range / not applied: invoiced units (only the scope's)


class SellInBonoSinAplicarOut(SellInBonoPedidoOut):
    """An operation of the scope invoiced inside the range that produced no active purchase, and why."""

    motivo: str  # the worker's queued error, "Sin líneas de ... en la factura", or "En cola"
    intentos: Optional[int]  # the worker's attempts when its key is queued, else None
    es_error: bool  # True when `motivo` is the worker's error, not a status


class SellInBonoSinAplicarListOut(BaseModel):
    total: int
    items: list[SellInBonoSinAplicarOut]


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
    sin_aplicar: SellInBonoSinAplicarListOut

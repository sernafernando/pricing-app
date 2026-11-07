"""Schemas of the tacticals API (`/api/tacticals`, tacticals T1). The contract T2 and T5 build against is
`handoffs/tactical-tarea.md` "Contrato final".

Only the shape is validated here (types, lengths, digits); the rules (each scope carries its own field, what each
engine accepts) live in `app.services.tacticals`, so they come back as a 422 with one Spanish message naming the line.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sell_out import RepartoCriterio

TipoTactical = Literal["sell_in", "sell_out"]
Alcance = Literal["productos", "marca", "categoria", "factura"]
ModoMonto = Literal["por_unidad", "porcentaje", "monto_total"]
Moneda = Literal["ARS", "USD"]
TcModo = Literal["al_cobro", "fijo", "dia_venta"]
Origen = Literal["sell_out_campana", "sell_in_bono", "sell_in_compra"]
EstadoFiltro = Literal["vigentes", "vencidos", "anulados"]
TipoTienda = Literal["oficial", "fuera", "tienda_nube"]

NOMBRE_MAX = 200
MARCA_MAX = 100  # productos_erp.marca is VARCHAR(100)
LINEAS_MAX = 100
ITEMS_MAX = 500
TIENDAS_MAX = 100  # official stores + synthetic channels on one tactical
NOTA_MAX = 2000
HIJOS_MAX = 500  # campaigns or bonuses one create may store: one per-product line over a full product list
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)
INT_MAX = 2**31 - 1
MONTO = {"max_digits": 18, "decimal_places": 2}


class TacticalTiendaIn(BaseModel):
    """One official store or synthetic channel the tactical applies to."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoTienda
    store_id: Optional[int] = Field(default=None, ge=1, le=2**63 - 1)


class TacticalTiendaOut(BaseModel):
    tipo: TipoTienda
    store_id: Optional[int] = None


class TacticalLineaIn(BaseModel):
    alcance: Alcance
    item_ids: list[int] = Field(default_factory=list, max_length=ITEMS_MAX)
    marca: Optional[str] = Field(default=None, max_length=MARCA_MAX)
    categoria: Optional[str] = Field(default=None, max_length=MARCA_MAX)
    pedido_compra_id: Optional[int] = Field(default=None, ge=1, le=2**63 - 1)
    modo_monto: ModoMonto
    # por_unidad / monto_total: in the tactical's `moneda`; porcentaje: (0, 100], checked by the service.
    valor: Decimal = Field(**MONTO)
    tope_unidades: Optional[int] = Field(default=None, ge=1, le=INT_MAX, strict=True)
    tope_monto: Optional[Decimal] = Field(default=None, **MONTO)  # in the tactical's `moneda`
    # Only on a `productos` line: one child per product, each with the whole `valor` and its own caps.
    tope_por_producto: bool = False
    # Required on a `monto_total` line over products, brand or category (sell out, and a sell in cost bonus) and
    # refused elsewhere, an invoice line included: how its total is split among the line's products
    # (`app.services.sell_out.criterio`).
    reparto_criterio: Optional[RepartoCriterio] = None


class TacticalIn(BaseModel):
    tipo: TipoTactical
    nombre: str = Field(max_length=NOMBRE_MAX)
    marca: str = Field(max_length=MARCA_MAX)
    referencia: Optional[str] = Field(default=None, max_length=NOMBRE_MAX)
    fecha_desde: date
    fecha_hasta: date  # inclusive
    moneda: Moneda
    tc_modo: Optional[TcModo] = None  # USD only; None means `al_cobro`
    tipo_cambio: Optional[Decimal] = Field(default=None, max_digits=18, decimal_places=6)  # `fijo` only
    incluye_iva: bool = False
    acumulable: bool = True
    # Store scope: True = every official store (no `oficial` rows); tiendas may still list channels.
    todas_tiendas: bool = True
    tope_compartido: bool = False  # False = per-target counters; True = one pool over the selection
    tiendas: list[TacticalTiendaIn] = Field(default_factory=list, max_length=TIENDAS_MAX)
    nota: Optional[str] = Field(default=None, max_length=NOTA_MAX)
    lineas: list[TacticalLineaIn] = Field(min_length=1, max_length=LINEAS_MAX)


class TacticalLineaTopesIn(BaseModel):
    """One line's caps on edit: a cap left out keeps the stored one, an explicit null removes it."""

    model_config = ConfigDict(extra="forbid")

    linea: int = Field(ge=1, le=LINEAS_MAX)  # its 1-based line; every child of a per-product line takes them
    tope_unidades: Optional[int] = Field(default=None, ge=1, le=INT_MAX, strict=True)
    tope_monto: Optional[Decimal] = Field(default=None, **MONTO)  # in the tactical's `moneda`


class TacticalEditarIn(BaseModel):
    """The fields safe on live money (tacticals F1); a field left out keeps its value. Lines, values, scope and the
    other header fields are not editable (an unknown field is a 422): changing them is Anular + Renovar."""

    model_config = ConfigDict(extra="forbid")

    nombre: Optional[str] = Field(default=None, max_length=NOMBRE_MAX)
    nota: Optional[str] = Field(default=None, max_length=NOTA_MAX)  # null or blank clears it
    fecha_hasta: Optional[date] = None  # inclusive; never before today nor before `fecha_desde`
    lineas: list[TacticalLineaTopesIn] = Field(default_factory=list, max_length=LINEAS_MAX)


class TacticalAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class TacticalProductoOut(BaseModel):
    item_id: int
    codigo: Optional[str]  # None when the catalog no longer has the item
    descripcion: Optional[str]


class TacticalLineaOut(BaseModel):
    """One per child row: a `tope_por_producto` line comes back as one line per product."""

    id: int  # the child row's id (campaign, bonus or purchase)
    linea: int  # its 1-based line in the tactical; the children of a per-product line share it
    origen: Origen
    estado: Literal["activa", "anulada"]
    alcance: Alcance
    productos: list[TacticalProductoOut]
    marca: Optional[str]
    categoria: Optional[str]
    pedido_compra_id: Optional[int]
    pedido_numero: Optional[str]
    modo_monto: ModoMonto
    valor: Decimal
    moneda: Moneda  # of `valor`, `tope_monto` and `monto_usado`
    tope_unidades: Optional[int]
    tope_monto: Optional[Decimal]
    tope_por_producto: bool  # its line created more than one child (one per product)
    reparto_criterio: Optional[RepartoCriterio] = None  # a `monto_total` line's split; None otherwise (invoice too)
    # A sell in total line of a USD tactical: the USD amount it was loaded with (`valor` is the bonus's ARS total,
    # converted at the tactical's fixed `tipo_cambio`); None on every other line.
    valor_usd: Optional[Decimal] = None
    unidades_usadas: int
    monto_usado: Decimal


class TacticalOut(BaseModel):
    id: int
    tipo: TipoTactical
    nombre: str
    marca: str
    referencia: Optional[str]
    fecha_desde: date
    fecha_hasta: date
    moneda: Moneda
    tc_modo: Optional[TcModo]
    tipo_cambio: Optional[Decimal]
    incluye_iva: bool
    acumulable: bool
    todas_tiendas: bool
    tope_compartido: bool
    tiendas: list[TacticalTiendaOut]
    nota: Optional[str]
    estado: Literal["activo", "anulado"]
    usuario_id: int
    created_at: datetime
    updated_at: datetime
    lineas: list[TacticalLineaOut]


class TacticalListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[TacticalOut]

"""Schemas of the tacticals API (`/api/tacticals`, tacticals T1). The contract T2 and T5 build against is
`handoffs/tactical-tarea.md` "Contrato final".

Only the shape is validated here (types, lengths, digits); the rules (each scope carries its own field, what each
engine accepts) live in `app.services.tacticals`, so they come back as a 422 with one Spanish message naming the line.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.sell_out import RepartoCriterio

TipoTactical = Literal["sell_in", "sell_out"]
Alcance = Literal["productos", "marca", "categoria", "factura"]
ModoMonto = Literal["por_unidad", "porcentaje", "monto_total"]
Moneda = Literal["ARS", "USD"]
TcModo = Literal["al_cobro", "fijo", "dia_venta"]
# `sell_in_factura_pendiente`: an invoice total still waiting for its invoice (`TacticalFacturaPendiente`).
Origen = Literal["sell_out_campana", "sell_in_bono", "sell_in_compra", "sell_in_factura_pendiente"]
EstadoFiltro = Literal["vigentes", "vencidos", "anulados"]
TipoTienda = Literal["oficial", "fuera", "tienda_nube"]
MedioCobro = Literal["nota_credito", "fondo_distribuidor", "otro"]
CobranzaFiltro = Literal["cobrados", "pendientes"]
ContieneFiltro = Literal["productos", "marca", "categoria", "factura"]  # a kind of line (SISO S1)

NOMBRE_MAX = 200
MARCA_MAX = 100  # productos_erp.marca is VARCHAR(100)
MARCAS_MAX = 50  # brands on one tactical header
LINEAS_MAX = 100
ITEMS_MAX = 500
FACTURAS_MAX = 100  # invoices one invoice line may pick out of its operation's
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
    # An invoice line only (sell in varias facturas S3): the invoices (`ct_transaction_id` of the operation's
    # `pedido_compra_facturas`) it applies to. None: every invoice of the operation, the ones linked later included.
    facturas_ct: Optional[list[Annotated[int, Field(ge=1, le=2**63 - 1)]]] = Field(
        default=None, max_length=FACTURAS_MAX
    )
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
    # The header's brands (S3, owner 2026-11-10: "selector multiple"). An old client sends only `marca`: it means
    # `marcas = [marca]`; when both come, `marca` must be one of `marcas` (checked by the service).
    marca: Optional[str] = Field(default=None, max_length=MARCA_MAX)
    marcas: list[str] = Field(default_factory=list, max_length=MARCAS_MAX)
    referencia: Optional[str] = Field(default=None, max_length=NOMBRE_MAX)
    # Required unless every line is an invoice line: then the service fills them from the invoices (oldest..newest).
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None  # inclusive
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

    @model_validator(mode="after")
    def _alcance_omitido(self) -> "TacticalIn":
        """A client that sends no scope at all (none of the three fields) keeps today's reach, as the migration's
        backfill: every official store plus outside sales and Tienda Nube, with one shared cap. The store picker
        always sends all three, so a tactical made there keeps per-target caps by default."""
        if not {"todas_tiendas", "tope_compartido", "tiendas"} & self.model_fields_set:
            self.tope_compartido = True
            self.tiendas = [TacticalTiendaIn(tipo="fuera"), TacticalTiendaIn(tipo="tienda_nube")]
        return self


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


class TacticalFacturaElegidaOut(BaseModel):
    ct_transaction_id: int
    numero: Optional[str] = None  # the readable ERP number (#2264); None when the mirror has none


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
    # A sell out `al_cobro` campaign: the rate already set when the brand paid; None on every other line (S8).
    tc_al_cobro: Optional[Decimal] = None
    unidades_usadas: int
    monto_usado: Decimal
    # An invoice line saved before Compras linked its operation's supplier invoice: it applies nothing until then.
    esperando_factura: bool = False
    # An invoice line's pick (S5): None = every invoice of its operation ("Todas"); otherwise the picked invoices.
    facturas_ct: Optional[list[int]] = None
    facturas_elegidas: Optional[list[TacticalFacturaElegidaOut]] = None


# Only the detail of the chosen `medio` may come (tactical cobranza S1, S2): one Spanish message per field.
_DETALLE_DE_MEDIO = (
    ("nc_numero", "nota_credito", "El número de NC va solo con el medio Nota de crédito"),
    ("distribuidor", "fondo_distribuidor", "El distribuidor va solo con el medio Fondo en distribuidor"),
    ("otro_detalle", "otro", "El detalle va solo con el medio Otro"),
)


class TacticalCobranzaIn(BaseModel):
    """Owner 2026-11-10: "pida, fecha de cuando se cobro, si es Nota de crédito (ahí número) o si es fondo en
    distribuidor (ahí un panel para aclarar el distri) u otro ... observaciones libre, que obligatorio sea la fecha no
    más". Blank texts are stored as NULL by the service."""

    fecha_cobro: date
    medio: Optional[MedioCobro] = None
    nc_numero: Optional[str] = Field(default=None, max_length=100)
    distribuidor: Optional[str] = Field(default=None, max_length=200)
    otro_detalle: Optional[str] = Field(default=None, max_length=500)
    observaciones: Optional[str] = Field(default=None, max_length=NOTA_MAX)

    @model_validator(mode="after")
    def _detalle_del_medio(self) -> "TacticalCobranzaIn":
        for campo, medio, mensaje in _DETALLE_DE_MEDIO:
            if (getattr(self, campo) or "").strip() and self.medio != medio:
                raise ValueError(mensaje)
        return self


class TacticalCobranzaOut(BaseModel):
    fecha_cobro: date
    medio: Optional[MedioCobro]
    nc_numero: Optional[str]
    distribuidor: Optional[str]
    otro_detalle: Optional[str]
    observaciones: Optional[str]
    usuario_id: int  # the last user to save it
    created_at: datetime
    updated_at: datetime


class TacticalOut(BaseModel):
    id: int
    tipo: TipoTactical
    nombre: str
    marca: str  # one of `marcas` (the one sent as `marca`, else the first), for a client that reads one brand
    marcas: list[str]
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
    # Every line is an invoice line: no dates of its own (each applies until its invoice's units are sold).
    por_factura: bool
    # Some active invoice line waits for its operation's supplier invoice ("Esperando factura" until Compras links it).
    esperando_factura: bool = False
    lineas: list[TacticalLineaOut]
    # The collection record (tactical cobranza S1): None = "Pendiente", a record = "Cobrado".
    cobranza: Optional[TacticalCobranzaOut] = None


class MontoMonedaOut(BaseModel):
    moneda: Moneda
    monto: Decimal
    tope: Optional[Decimal] = None  # the lines' money caps in this currency (S6); None when no line here has one
    tope_parcial: bool = False  # only some lines in this currency have a cap: `tope` is not comparable to `monto`


class CobranzaKpiOut(BaseModel):
    cantidad: int
    sin_tope: int = 0  # how many have no money cap on any line (S6)
    montos: list[MontoMonedaOut]  # money used per currency, as the list's Avance column (ARS first)


class TacticalKpisOut(BaseModel):
    pendientes: CobranzaKpiOut
    cobrados: CobranzaKpiOut


class TacticalListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[TacticalOut]
    # Over every tactical the other filters match (not only this page, not the collection filter): S4.
    kpis: TacticalKpisOut

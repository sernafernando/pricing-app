"""Schemas of the sell-out campaigns API (`/api/sell-out/campanas`) and its programs (`/api/sell-out/programas`).

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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    SerializerFunctionWrapHandler,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic_core import InitErrorDetails

Tipo = Literal["por_unidad", "porcentaje", "monto_total"]
BasePorcentaje = Literal["costo", "precio_neto"]
Moneda = Literal["ARS", "USD"]
TcModo = Literal["al_cobro", "fijo", "dia_venta"]
Estado = Literal["activa", "anulada"]
Canal = Literal["ml", "fuera", "tn"]
EstadoRecalculo = Literal["al_dia", "en_cola", "recalculando", "fallida"]
EstadoPrograma = Literal["activo", "archivado"]

NOMBRE_MAX = 200
MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)
GRUPOS_MAX = 50
ITEMS_MAX = 500
ASIGNAR_MAX = 500  # campaigns per program assignment
INT_MIN, INT_MAX = -(2**31), 2**31 - 1  # INTEGER

# Each NUMERIC(precision, scale) column as (max_digits, decimal_places).
MONTO = {"max_digits": 18, "decimal_places": 2}  # monto_unit, tope_monto, monto_total, reparto_monto: NUMERIC(18, 2)
PORCENTAJE = {"max_digits": 7, "decimal_places": 4}  # NUMERIC(7, 4)
TIPO_CAMBIO = {"max_digits": 18, "decimal_places": 6}  # NUMERIC(18, 6)


class SellOutCampanaItemIn(BaseModel):
    """A product's own amount per unit in a `por_unidad` campaign (T22b: legacy grouped offsets), in `moneda`,
    loaded with VAT or not like `monto_unit`. It replaces `monto_unit` for that product only; the cap is shared.

    In a `monto_total` campaign (T26c) it is the product's share of the total instead: `reparto_porcentaje` (a % of
    the total) or `reparto_monto` (a fixed amount in `moneda`, with the total's sign), exactly one, no `monto_unit`."""

    item_id: int = Field(ge=INT_MIN, le=INT_MAX)
    monto_unit: Optional[Decimal] = Field(default=None, **MONTO)
    reparto_porcentaje: Optional[Decimal] = Field(default=None, **PORCENTAJE)
    reparto_monto: Optional[Decimal] = Field(default=None, **MONTO)


# Keys only a `monto_total` campaign returns: the other types' responses keep their shape, byte for byte.
_SOLO_MONTO_TOTAL = ("reparto_porcentaje", "reparto_monto")


class SellOutCampanaItemOut(BaseModel):
    item_id: int
    monto_unit: Optional[Decimal]  # None for a share of a `monto_total` campaign
    codigo: Optional[str] = None  # the product, for the screen; None if it left the ERP catalog
    descripcion: Optional[str] = None
    reparto_porcentaje: Optional[Decimal] = None  # `monto_total` only, like `reparto_monto`
    reparto_monto: Optional[Decimal] = None

    @model_serializer(mode="wrap")
    def _sin_reparto(self, handler: SerializerFunctionWrapHandler) -> dict:
        salida = handler(self)
        if self.monto_unit is not None:  # a per-unit amount, not a share
            for clave in _SOLO_MONTO_TOTAL:
                salida.pop(clave, None)
        return salida


class SellOutRepartoIn(BaseModel):
    """`PUT /{id}/reparto`: the shares of a `monto_total` campaign (see `SellOutCampanaItemIn`). An admin or a
    `sell_out.gestionar` user replaces them all; a PM only those of their brands, the rest are kept."""

    repartos: list[SellOutCampanaItemIn] = Field(max_length=ITEMS_MAX)


class SellOutCampanaIn(BaseModel):
    """Create, and full replace on edit; also the renewal draft (`GET /{id}/renovacion`)."""

    nombre: str = Field(max_length=NOMBRE_MAX)
    descripcion: Optional[str] = None
    fecha_desde: date
    fecha_hasta: date  # inclusive
    tipo: Tipo
    monto_unit: Optional[Decimal] = Field(default=None, **MONTO)  # per unit, in `moneda`; only for `por_unidad`
    # The campaign's one amount, in `moneda`, never 0 (negative: a deduction); only for `monto_total`
    monto_total: Optional[Decimal] = Field(default=None, **MONTO)
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
    # Products of the groups with their own amount (`por_unidad`; the rest get `monto_unit`) or their share
    # (`monto_total`, see `SellOutCampanaItemIn`). Absent (None)
    # keeps the stored ones, so a client that does not send them never wipes them; `[]` clears them.
    items: Optional[list[SellOutCampanaItemIn]] = Field(default=None, max_length=ITEMS_MAX)
    # Its program (campaign system S1), on create only: absent or None means none. An edit ignores it and keeps the
    # stored one; assignment goes through `POST /api/sell-out/programas/asignar`, which audits it.
    programa_id: Optional[int] = Field(default=None, ge=INT_MIN, le=INT_MAX)
    # The campaign it renews (the renewal draft sets it), on create only like `programa_id`: an edit keeps the stored one.
    renovada_de_id: Optional[int] = Field(default=None, ge=1, le=2**63 - 1)

    @model_validator(mode="wrap")
    @classmethod
    def _monto_unit_requerido(cls, data, handler: ModelWrapValidatorHandler["SellOutCampanaIn"]):
        """Outside `monto_total`, an item without `monto_unit` (and without a share, which gets its own readable
        422) is pydantic's field-required error, as it was before `monto_unit` became optional for the shares
        (same type, location and message)."""
        items = data.get("items") if isinstance(data, dict) and data.get("tipo") != "monto_total" else None
        if isinstance(items, list):
            faltan = [
                InitErrorDetails(type="missing", loc=("items", i, "monto_unit"), input=item)
                for i, item in enumerate(items)
                if isinstance(item, dict) and not {"monto_unit", "reparto_porcentaje", "reparto_monto"} & item.keys()
            ]
            if faltan:
                raise ValidationError.from_exception_data(cls.__name__, faltan)
        return handler(data)


class SellOutAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class SellOutAnularMasivoIn(BaseModel):
    ids: list[int]  # empty or over `ANULAR_MASIVO_MAX` is refused by the router with a readable message
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class SellOutAnularMasivoOut(BaseModel):
    anuladas: list[int]
    omitidas: list[int]  # already voided: skipped, not an error


class SellOutEditarMasivoIn(BaseModel):
    """`POST /editar-masivo[/previa]`: the campaigns and the fields to set on all of them; an absent or null field
    is not filled and keeps each campaign's stored value. An empty or too large selection, or no field filled, is
    refused by the router with a readable message. Any other field (another column, a typo) is a 422: never
    silently dropped."""

    model_config = ConfigDict(extra="forbid")

    campana_ids: list[int]
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None  # inclusive
    acumulable: Optional[bool] = None

    def cambios(self) -> dict:
        """The filled fields only (`edicion_masiva.CAMPOS`)."""
        return {
            campo: valor
            for campo in ("fecha_desde", "fecha_hasta", "acumulable")
            if (valor := getattr(self, campo)) is not None
        }


class SellOutEditarMasivoOut(BaseModel):
    editadas: list[int]
    sin_cambio: list[int]  # already had the values: no audit row, not queued


class SellOutEdicionRechazadaOut(BaseModel):
    id: int
    nombre: Optional[str]  # None for an unknown id
    motivo: str


class SellOutEdicionMovimientoOut(BaseModel):
    """What the rebuild after the edit takes from (`salen`) or gives to (`entran`) one campaign, simulated with the
    drain's own rebuild and rolled back (`edicion_masiva`): lines gone (or new), and the units and money, in the
    campaign currency, its lines lose (or gain). Exact on the same data: caps, stacking and a fixed total's split
    included (a `monto_total` share moved between a product's sales shows on both sides). `monto` is the signed
    credit of the lines that leave or shrink (`salen`) or enter or grow (`entran`), kept on the line's side: a
    deduction's (negative `monto_total`) leaving -100 line is `salen` -100, not `entran` +100."""

    lineas: int
    unidades: int
    monto: Decimal


class SellOutEdicionCampanaPreviaOut(BaseModel):
    id: int
    nombre: str
    moneda: Moneda
    # The values the campaign would have.
    fecha_desde: date
    fecha_hasta: date
    acumulable: bool
    incluye_pendientes: bool = Field(
        description=(
            "It had a queue row before the preview: its numbers also include pending work this edit does not "
            "cause («incluye cambios pendientes que no causa esta edición»)."
        )
    )
    salen: SellOutEdicionMovimientoOut
    entran: SellOutEdicionMovimientoOut


class SellOutEdicionVinculadaPreviaOut(BaseModel):
    """A campaign the edit does not change but whose credit the rebuild moves: it shares products with an edited one
    (a cap or `acumulable` decides who holds the units)."""

    id: int
    nombre: str
    moneda: Moneda
    en_seleccion: bool  # False: not among the selected campaigns
    incluye_pendientes: bool = Field(
        description=(
            "It had a queue row before the preview: its numbers also include pending work this edit does not "
            "cause («incluye cambios pendientes que no causa esta edición»)."
        )
    )
    salen: SellOutEdicionMovimientoOut
    entran: SellOutEdicionMovimientoOut


class SellOutEdicionMontoOut(BaseModel):
    moneda: Moneda
    monto: Decimal


class SellOutEdicionMovimientoTotalOut(BaseModel):
    lineas: int
    unidades: int
    montos: list[SellOutEdicionMontoOut]  # per currency, only the currencies with something that moves


class SellOutEdicionTotalesOut(BaseModel):
    cambian: int
    sin_cambio: int
    rechazadas: int
    salen: SellOutEdicionMovimientoTotalOut  # over `cambian` and `vinculadas`
    entran: SellOutEdicionMovimientoTotalOut


class SellOutEdicionPreviaOut(BaseModel):
    """What the bulk edit and the rebuild it queues would do on the same data, written nothing. While `rechazadas`
    is not empty the apply refuses it all; the numbers are those of the campaigns that can be edited."""

    totales: SellOutEdicionTotalesOut
    cambian: list[SellOutEdicionCampanaPreviaOut]
    vinculadas: list[SellOutEdicionVinculadaPreviaOut]
    # «incluye cambios pendientes que no causa esta edición» when any campaign the rebuild touches has pending work
    # (a queue row before the preview), listed or not: a voided one not drained yet included; else None.
    aviso_pendientes: Optional[str] = None
    sin_cambio: list[int]
    rechazadas: list[SellOutEdicionRechazadaOut]


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


class SellOutRepartoResumenOut(BaseModel):
    """A `monto_total` campaign's split (`reparto.resumen_monto_total`), in the campaign currency: what its shares
    assign (`asignado`), the shares of products without sales in the dates (`asignado_sin_ventas`) and the total
    nobody was given (`sin_asignar`). None amounts: the stored shares cannot be split as they stand, and `motivo`
    says why (else None)."""

    asignado: Optional[Decimal]
    asignado_sin_ventas: Optional[Decimal]
    sin_asignar: Optional[Decimal]
    motivo: Optional[str] = None


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
    reparto: Optional[SellOutRepartoResumenOut] = None  # `monto_total` only (absent on the other types)

    @model_serializer(mode="wrap")
    def _sin_reparto(self, handler: SerializerFunctionWrapHandler) -> dict:
        salida = handler(self)
        if self.reparto is None:
            salida.pop("reparto", None)
        return salida


class SellOutProgramaRefOut(BaseModel):
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
    monto_total: Optional[Decimal] = None  # `monto_total` only (absent on the other types)
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
    # Its program (metadata only), set with `POST /api/sell-out/programas/asignar`, never by an edit.
    programa_id: Optional[int] = None
    renovada_de_id: Optional[int] = None
    # read-only: the tactical it is a line of; its own hidden group is never in `grupos` (the edit step keeps it)
    tactical_id: Optional[int] = None
    programa: Optional[SellOutProgramaRefOut] = None
    created_at: datetime
    updated_at: datetime
    grupos: list[SellOutGrupoOut]
    items: list[SellOutCampanaItemOut] = []  # the products with their own amount or share, by item_id
    resumen: SellOutResumenOut

    @model_serializer(mode="wrap")
    def _sin_monto_total(self, handler: SerializerFunctionWrapHandler) -> dict:
        salida = handler(self)
        if self.tipo != "monto_total":
            salida.pop("monto_total", None)
        return salida


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


# ── Programs (`/api/sell-out/programas`, campaign system S1) ───────────


def _nombre_programa(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        raise ValueError("El nombre del programa no puede estar vacío.")
    if len(valor) > NOMBRE_MAX:  # counted after trimming: surrounding spaces never make a name too long
        raise ValueError(f"El nombre del programa admite hasta {NOMBRE_MAX} caracteres.")
    return valor


class SellOutProgramaIn(BaseModel):
    """`POST /`: a new program. The name is trimmed, not empty and unique ignoring case (a 409 otherwise)."""

    nombre: str
    descripcion: Optional[str] = None

    _nombre = field_validator("nombre")(_nombre_programa)


class SellOutProgramaPatchIn(BaseModel):
    """`PATCH /{id}`: only the fields sent change. `nombre` and `estado` cannot be null; `descripcion` can."""

    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    estado: Optional[EstadoPrograma] = None

    _nombre = field_validator("nombre")(_nombre_programa)

    @model_validator(mode="after")
    def _sin_nulos(self) -> "SellOutProgramaPatchIn":
        for campo in ("nombre", "estado"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"El campo {campo} no puede ser nulo.")
        return self


class SellOutProgramaOut(BaseModel):
    """A program with what its campaigns span: how many (`campanas`), how many are active (`activas`), the
    earliest start (`desde`) and the latest end (`hasta`); None dates while it has no campaign."""

    id: int
    nombre: str
    descripcion: Optional[str]
    estado: EstadoPrograma
    campanas: int
    activas: int
    desde: Optional[date]
    hasta: Optional[date]
    nombres: int  # distinct campaign names, ignoring case and repeated spaces


class SellOutAsignarIn(BaseModel):
    """`POST /asignar`: set the program of these campaigns, or clear it with `programa_id: null` (required)."""

    campana_ids: list[int] = Field(min_length=1, max_length=ASIGNAR_MAX)
    programa_id: Optional[int]


class SellOutAsignarOut(BaseModel):
    asignadas: int  # campaigns whose program changed
    sin_cambio: int  # already had it


class SellOutRenovarCampanaOut(BaseModel):
    campana_id: int
    nombre: str
    nombre_nuevo: str  # the copy's name: its trailing period advanced (`renovacion.nombre_renovado`)


class SellOutRenovacionOmitidaOut(BaseModel):
    campana_id: int
    nombre: str
    motivo: str  # "anulada, no se renueva" or "ya renovada en la campaña N (nombre)"


class SellOutQuedaAfueraOut(BaseModel):
    campana_id: int
    nombre: str
    fecha_hasta: date


class SellOutRenovacionProgramaOut(BaseModel):
    """`GET /{id}/renovacion`: what Renovar programa would do (`renovacion_programa.previa`): the source period
    (`periodo_desde`, `periodo_hasta`), the target quarter (`fecha_desde`, `fecha_hasta`), the campaigns renewed,
    the skipped ones with why, and the not-renewed ones of the other quarter of the window, left for a later pass.
    The dates are None, with nothing to renew, when the program has no campaigns."""

    programa_id: int
    programa: str
    periodo_desde: Optional[date]
    periodo_hasta: Optional[date]
    fecha_desde: Optional[date]
    fecha_hasta: Optional[date]
    renovar: list[SellOutRenovarCampanaOut]
    omitidas: list[SellOutRenovacionOmitidaOut]
    quedan_afuera: list[SellOutQuedaAfueraOut]


class SellOutRenovarProgramaIn(BaseModel):
    """`POST /{id}/renovar`: the campaign ids the preview listed under `renovar`."""

    campana_ids: list[int] = Field(min_length=1, max_length=ASIGNAR_MAX)


class SellOutRenovadaOut(BaseModel):
    campana_id: int  # the original
    nueva_id: int  # its copy


class SellOutRenovarProgramaOut(BaseModel):
    creadas: list[SellOutRenovadaOut]
    omitidas: list[SellOutRenovacionOmitidaOut]


class SellOutSugerenciaCampanaOut(BaseModel):
    id: int
    nombre: str
    fecha_desde: date
    fecha_hasta: date
    estado: Estado


class SellOutSugerenciaOut(BaseModel):
    """Campaigns without a program sharing their exact dates (`programas.sugerencias`): a proposal, never applied.
    `base` is the proposed program name, `nombres` how many distinct names the group holds."""

    base: str
    fecha_desde: date
    fecha_hasta: date
    nombres: int
    campanas: list[SellOutSugerenciaCampanaOut]


class SellOutProgramaListOut(BaseModel):
    items: list[SellOutProgramaOut]
    total: int
    page: int
    page_size: int


class SellOutSugerenciaListOut(BaseModel):
    items: list[SellOutSugerenciaOut]
    total: int
    page: int
    page_size: int


class SellOutGrupoProgramaOut(BaseModel):
    """A row of the grouped view (`GET /sell-out/campanas/por-programa`): a program (or, with `programa_id` None,
    the campaigns without one) and what its campaigns under the list's filters span."""

    programa_id: Optional[int]
    nombre: Optional[str]
    campanas: int
    activas: int
    nombres: int  # distinct campaign names, ignoring case and repeated spaces
    desde: date
    hasta: date


class SellOutGruposProgramaListOut(BaseModel):
    items: list[SellOutGrupoProgramaOut]  # programs with campaigns under the filters, by name
    total: int
    page: int
    page_size: int
    sin_programa: Optional[SellOutGrupoProgramaOut]  # None when every filtered campaign has a program

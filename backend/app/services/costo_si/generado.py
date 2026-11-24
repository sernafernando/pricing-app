"""What each sell in took off the purchase invoices in costo SI (sell-in-costo-si T5 PR B, owner L26 "recalculalo").

A cost bonus (`base='costo_venta'`) and a tactical's invoice total (a `sell_in_compras` row) no longer lower each
sale: costo SI applies them to the purchase invoices of their period. What they "used" or "generated" is read back
from the stored purchase steps (`costo_si_pasos`, type `compra`): each step lists the sell ins it got
(`sell_ins`: `[{origen, ref, porcentaje}]`, `origen` 'bono' for `sell_in_bonos_marca.id`, 'compra' for
`sell_in_compras.id`), with the % already cut by the line's caps (`fuentes.aplicar_topes`).

- Amount of one sell in on one step: `cantidad x costo_neto x porcentaje / 100`, in the step's currency (the
  product's cost currency, L18).
- In the sell in's own currency: as it is when they match; otherwise at the invoice's rate as the line's caps used it
  (`fuentes.sql_tc_factura`: the PM's correction, the Compras operation's TC, the last rate on or before its date), so
  what is left of a money cap never drifts from what costo SI used up. A step with no rate at all adds no amount,
  never a 0 taken as real (§7).
- A step whose cost is unknown has no amount either: NULL, left out of every sum, never a 0 (§7). Each one is logged
  with its item and date, so the gap can be found.
- Units: a Compras sell in, the step's units. A brand bonus, the units its amount covered: the step's units x the %
  it got / the % it would get uncapped (its own or its model's %, or its amount per unit over the unit price; net of
  the product's VAT when it includes it; never over the purchase itself), so a cap (units or money) that ran out
  inside an invoice counts only the units it covered, and never more than its `tope_unidades`.

Postgres only: the JSONB list is expanded with `jsonb_array_elements`.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from sqlalchemy import (
    Integer,
    Numeric,
    Select,
    and_,
    case,
    cast,
    distinct,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.costo_si import CostoSiPaso
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoItem, SellInBonoMarca, SellInCompra
from app.services.costo_si.fuentes import sql_tc_factura

logger = logging.getLogger(__name__)

BONO = "bono"
COMPRA = "compra"

# Ids of the sell ins asked for: a list, or a select of them.
Refs = Iterable[int] | Select


def _sell_ins(bonos: Refs | None = None, compras: Refs | None = None):
    """One row per (purchase step, sell in it got) of the brand bonuses in `bonos` and the Compras sell ins in
    `compras` (ids, or a select of them): `origen`, `ref`, `item_id`, `fecha`, `unidades`, `porcentaje`, `precio` and
    `monto` (in the step's currency; NULL when its cost is unknown), `moneda` (the step's), `tc` (ARS per USD to change
    it). The filter sits inside, so each step's rate (`sql_tc_factura`) is looked up only for the rows asked for."""
    p = CostoSiPaso
    s = func.jsonb_array_elements(p.sell_ins).table_valued("value").alias("s")

    def campo(clave: str) -> ColumnElement:
        return s.c.value.op("->>")(clave)

    tabla = p.__tablename__
    tasa = literal_column(sql_tc_factura(f"{tabla}.ct_transaction", f"{tabla}.fecha"))
    porcentaje = cast(campo("porcentaje"), Numeric(9, 4))
    # An unknown cost stays NULL, so the step's amount is left out of every sum (§7).
    precio = p.costo_neto_usd
    origen, ref = campo("origen"), cast(campo("ref"), Integer)
    pedidos = [and_(origen == o, ref.in_(ids)) for o, ids in ((BONO, bonos), (COMPRA, compras)) if ids is not None]
    return (
        select(
            origen.label("origen"),
            ref.label("ref"),
            p.item_id.label("item_id"),
            p.fecha.label("fecha"),
            p.cantidad.label("unidades"),
            porcentaje.label("porcentaje"),
            precio.label("precio"),
            (p.cantidad * precio * porcentaje / 100).label("monto"),
            p.moneda.label("moneda"),
            # `tipo_cambio.venta` is a float: Numeric, so the amounts stay exact decimals.
            cast(tasa, Numeric(18, 6)).label("tc"),
        )
        .select_from(p)
        .join(s, true())
        .where(p.tipo == "compra", or_(*pedidos))
        .subquery("sell_ins_de_pasos")
    )


def _en(filas, moneda: ColumnElement, valor: ColumnElement | None = None) -> ColumnElement:
    """A row's amount (or `valor`, in the step's currency) in `moneda`: NULL (left out of a sum) when it needs a rate
    and has none."""
    valor = filas.c.monto if valor is None else valor
    return case(
        (filas.c.moneda == moneda, valor),
        (moneda == "USD", valor / filas.c.tc),
        else_=valor * filas.c.tc,
    )


def _unidades_de_bono(filas) -> ColumnElement:
    """The units of a step a brand bonus's amount covered (see the module docstring); the whole step when its uncapped
    % cannot be told (a unit price with no rate)."""
    b = SellInBonoMarca
    sin_iva = case(
        (b.incluye_iva.is_(True), 1 + cast(func.coalesce(ProductoERP.iva, 0), Numeric(9, 4)) / 100), else_=literal(1)
    )
    precio = _en(filas, b.moneda, filas.c.precio)
    entero = case(
        (b.tipo == "porcentaje", func.coalesce(SellInBonoItem.porcentaje, b.porcentaje) / sin_iva),
        (
            and_(b.tipo == "por_unidad", precio > 0),
            func.coalesce(SellInBonoItem.monto_unit, b.monto_unit) / sin_iva / precio * 100,
        ),
    )
    entero = case((entero > 100, literal(100)), else_=entero)
    return case((entero > 0, func.round(filas.c.unidades * filas.c.porcentaje / entero)), else_=filas.c.unidades)


def _sin_costo(filas) -> ColumnElement:
    """The steps with no cost among the grouped rows, as 'item N on YYYY-MM-DD' (a NULL entry stands for the rest)."""
    return func.array_agg(
        distinct(case((filas.c.precio.is_(None), func.concat("item ", filas.c.item_id, " on ", filas.c.fecha))))
    ).label("sin_costo")


def _avisar(origen: str, ref: int, pasos) -> None:
    for paso in sorted(p for p in pasos or () if p):
        logger.warning("costo SI: %s %s got a step with no cost (%s); its amount is left out", origen, ref, paso)


def por_bono(bonos: Refs) -> Select:
    """`(bono_id, unidades, monto, sin_costo)` per brand bonus in `bonos` some step got, the amount in the bonus's
    currency (unrounded)."""
    filas = _sell_ins(bonos=bonos)
    unidades = func.sum(_unidades_de_bono(filas))
    tope = SellInBonoMarca.tope_unidades
    return (
        select(
            SellInBonoMarca.id.label("bono_id"),
            case((and_(tope.isnot(None), unidades > tope), tope), else_=unidades).label("unidades"),
            func.sum(_en(filas, SellInBonoMarca.moneda)).label("monto"),
            _sin_costo(filas),
        )
        .join(filas, and_(filas.c.origen == BONO, filas.c.ref == SellInBonoMarca.id))
        .outerjoin(
            SellInBonoItem,
            and_(SellInBonoItem.bono_id == SellInBonoMarca.id, SellInBonoItem.item_id == filas.c.item_id),
        )
        .outerjoin(ProductoERP, ProductoERP.item_id == filas.c.item_id)
        .group_by(SellInBonoMarca.id, tope)
    )


def por_compra(compras: Refs) -> Select:
    """`(compra_id, unidades, monto, sin_costo)` per Compras sell in in `compras` some step got, the amount in the
    purchase's currency."""
    filas = _sell_ins(compras=compras)
    return (
        select(
            SellInCompra.id.label("compra_id"),
            func.sum(filas.c.unidades).label("unidades"),
            func.sum(_en(filas, SellInCompra.moneda)).label("monto"),
            _sin_costo(filas),
        )
        .join(filas, and_(filas.c.origen == COMPRA, filas.c.ref == SellInCompra.id))
        .group_by(SellInCompra.id)
    )


def _leer(db: Session, consulta: Select, origen: str) -> dict[int, tuple[int, Decimal]]:
    salida = {}
    for ref, unidades, monto, sin_costo in db.execute(consulta):
        _avisar(origen, ref, sin_costo)
        salida[ref] = (int(unidades or 0), Decimal(str(monto or 0)))
    return salida


def de_bonos(db: Session, ids: Iterable[int]) -> dict[int, tuple[int, Decimal]]:
    """`{bono id: (units, amount in its currency)}`; a bonus no step got is left out. A step with no cost is logged."""
    ids = list(ids)
    return _leer(db, por_bono(ids), BONO) if ids else {}


def de_compras(db: Session, ids: Iterable[int]) -> dict[int, tuple[int, Decimal]]:
    """`{sell_in_compras id: (units, amount in its currency)}`; a purchase no step got is left out. A step with no cost
    is logged."""
    ids = list(ids)
    return _leer(db, por_compra(ids), COMPRA) if ids else {}


def de_tacticals(tacticals: Select) -> tuple[Select, Select]:
    """The ids of the brand bonuses and of the Compras sell ins of the tacticals in `tacticals` (a select of ids)."""
    return (
        select(SellInBonoMarca.id).where(SellInBonoMarca.tactical_id.in_(tacticals)),
        select(SellInCompra.id).where(SellInCompra.tactical_id.in_(tacticals)),
    )


def avisar_sin_costo(db: Session, tacticals: Select) -> None:
    """Log each step with no cost that a sell in of the tacticals in `tacticals` (a select of their ids) got, whose
    amount a sum over them (the KPIs) leaves out: one query."""
    bonos, compras = de_tacticals(tacticals)
    filas = _sell_ins(bonos=bonos, compras=compras)
    consulta = (
        select(filas.c.origen, filas.c.ref, _sin_costo(filas))
        .where(filas.c.precio.is_(None))
        .group_by(filas.c.origen, filas.c.ref)
    )
    for origen, ref, pasos in db.execute(consulta):
        _avisar(origen, ref, pasos)

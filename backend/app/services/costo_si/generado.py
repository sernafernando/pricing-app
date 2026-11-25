"""What each sell in took off the purchase invoices in costo SI (sell-in-costo-si T5 PR B, owner L26 "recalculalo").

A cost bonus (`base='costo_venta'`) and a tactical's invoice total (a `sell_in_compras` row) no longer lower each
sale: costo SI applies them to the purchase invoices of their period. What they "used" or "generated" is read back
from the stored steps (`costo_si_pasos`: the purchases, type `compra`, and the stock on hand a brand bonus landed on
on its first day, types `inicio` / `sell_in`, owner L41): each step lists the sell ins it got
(`sell_ins`: `[{origen, ref, porcentaje}]`, `origen` 'bono' for `sell_in_bonos_marca.id`, 'compra' for
`sell_in_compras.id`), with the % already cut by the line's caps (`fuentes.aplicar_topes`).

- Amount of one sell in on one step: `cantidad x costo_neto x porcentaje / 100`, in the step's currency (the
  product's cost currency, L18).
- A brand bonus's % with no money cap stays in each step's currency, one amount per currency (sell in incident
  2026-11-24, S1: a % has no currency; "TP loyalty 18.18M ARS must read USD 11,648").
- Any other sell in, in its own currency: as it is when they match; otherwise at the invoice's rate as the line's caps used it
  (`fuentes.sql_tc_factura`: the PM's correction, the Compras operation's TC, the last rate on or before its date), so
  what is left of a money cap never drifts from what costo SI used up. A step with no rate at all adds no amount,
  never a 0 taken as real (§7).
- A step whose cost is unknown has no amount either: NULL, left out of every sum, never a 0 (§7). Each one is logged
  with its item and date, so the gap can be found.
- Units: a Compras sell in, the step's units; the stock on hand, its units on hand (`stock_base`, never below 0). A brand bonus, the units its amount covered: the step's units x the %
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
EN_MANO = ("inicio", "sell_in")  # the steps of the stock on hand a brand bonus landed on (L41)

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
    unidades = case((p.tipo.in_(EN_MANO), p.stock_base), else_=p.cantidad)
    pedidos = [and_(origen == o, ref.in_(ids)) for o, ids in ((BONO, bonos), (COMPRA, compras)) if ids is not None]
    return (
        select(
            origen.label("origen"),
            ref.label("ref"),
            p.item_id.label("item_id"),
            p.fecha.label("fecha"),
            unidades.label("unidades"),
            porcentaje.label("porcentaje"),
            precio.label("precio"),
            (unidades * precio * porcentaje / 100).label("monto"),
            p.moneda.label("moneda"),
            # `tipo_cambio.venta` is a float: Numeric, so the amounts stay exact decimals.
            cast(tasa, Numeric(18, 6)).label("tc"),
        )
        .select_from(p)
        .join(s, true())
        .where(p.tipo.in_((COMPRA, *EN_MANO)), or_(*pedidos))
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


def _en_moneda_del_paso() -> ColumnElement:
    """Whether a brand bonus's amount stays in each step's currency (sell in incident 2026-11-24, S1): a % with no
    money cap has no currency of its own (a USD tactical's is stored ARS, `tacticals.moneda_de_costo`), so what it
    took is the product's cost currency, one amount per currency, never converted. A per-unit amount, a total and a
    money cap are in the bonus's currency: those still count in it."""
    b = SellInBonoMarca
    return and_(b.tipo == "porcentaje", b.tope_monto.is_(None))


def por_bono(bonos: Refs) -> Select:
    """`(bono_id, moneda, unidades, monto, sin_costo)` per brand bonus in `bonos` some step got and currency its amount
    is in (`_en_moneda_del_paso`: the steps' own, or the bonus's), unrounded. `unidades` are that currency's steps'
    (not capped: `de_bonos` caps the bonus's total by its `tope_unidades`)."""
    filas = _sell_ins(bonos=bonos)
    propia = _en_moneda_del_paso()
    moneda = case((propia, filas.c.moneda), else_=SellInBonoMarca.moneda)
    return (
        select(
            SellInBonoMarca.id.label("bono_id"),
            moneda.label("moneda"),
            func.sum(_unidades_de_bono(filas)).label("unidades"),
            func.sum(case((propia, filas.c.monto), else_=_en(filas, SellInBonoMarca.moneda))).label("monto"),
            _sin_costo(filas),
            SellInBonoMarca.tope_unidades.label("tope"),
        )
        .join(filas, and_(filas.c.origen == BONO, filas.c.ref == SellInBonoMarca.id))
        .outerjoin(
            SellInBonoItem,
            and_(SellInBonoItem.bono_id == SellInBonoMarca.id, SellInBonoItem.item_id == filas.c.item_id),
        )
        .outerjoin(ProductoERP, ProductoERP.item_id == filas.c.item_id)
        .group_by(SellInBonoMarca.id, moneda, SellInBonoMarca.tope_unidades)
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


def de_bonos(db: Session, ids: Iterable[int]) -> dict[int, tuple[int, dict[str, Decimal]]]:
    """`{bono id: (units, {currency: amount})}`, the amount in each currency it is in (`por_bono`), the units over
    every currency, never over its `tope_unidades`; a bonus no step got is left out. A step with no cost is logged."""
    ids = list(ids)
    salida: dict[int, tuple[int, dict[str, Decimal]]] = {}
    for ref, moneda, unidades, monto, sin_costo, tope in db.execute(por_bono(ids)) if ids else ():
        _avisar(BONO, ref, sin_costo)
        antes, montos = salida.get(ref, (0, {}))
        total = antes + int(unidades or 0)
        montos[moneda] = Decimal(str(monto or 0))
        salida[ref] = (min(total, tope) if tope is not None else total, montos)
    return salida


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

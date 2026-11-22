"""What each sell in took off the purchase invoices in costo SI (sell-in-costo-si T5 PR B, owner L26 "recalculalo").

A cost bonus (`base='costo_venta'`) and a tactical's invoice total (a `sell_in_compras` row) no longer lower each
sale: costo SI applies them to the purchase invoices of their period. What they "used" or "generated" is read back
from the stored purchase steps (`costo_si_pasos`, type `compra`): each step lists the sell ins it got
(`sell_ins`: `[{origen, ref, porcentaje}]`, `origen` 'bono' for `sell_in_bonos_marca.id`, 'compra' for
`sell_in_compras.id`), with the % already cut by the line's caps (`fuentes.aplicar_topes`).

- Amount of one sell in on one step: `cantidad x costo_neto x porcentaje / 100`, in the step's currency (the
  product's cost currency, L18).
- In the sell in's own currency: as it is when they match; otherwise at the invoice's own rate (`tipo_cambio`, set when
  the invoice was in the other currency), else the last USD selling rate on or before the step's date, as costo SI
  does for an invoice without one. A step with no rate at all adds no amount, never a 0 taken as real (§7).
- Units: the step's units. A units cap that ran out inside an invoice covers only part of it, so a sell in's units
  never go above its `tope_unidades`.

Both dialects: Postgres expands the JSONB list with `jsonb_array_elements`, SQLite (the router tests) with
`json_each`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from sqlalchemy import Integer, Numeric, Select, and_, case, cast, func, literal, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.costo_si import CostoSiPaso
from app.models.sell_in import SellInBonoMarca, SellInCompra
from app.models.tipo_cambio import TipoCambio

BONO = "bono"
COMPRA = "compra"


def _sell_ins(dialect: str):
    """One row per (purchase step, sell in it got): `origen`, `ref`, `unidades`, `monto` (in the step's currency),
    `moneda` (the step's), `tc` (ARS per USD to change it)."""
    p = CostoSiPaso
    if dialect == "postgresql":
        s = func.jsonb_array_elements(p.sell_ins).table_valued("value").alias("s")

        def campo(clave: str) -> ColumnElement:
            return s.c.value.op("->>")(clave)

    else:
        s = func.json_each(p.sell_ins).table_valued("value").alias("s")

        def campo(clave: str) -> ColumnElement:
            return func.json_extract(s.c.value, f"$.{clave}")

    tasa = (
        select(TipoCambio.venta)
        .where(TipoCambio.moneda == "USD", TipoCambio.venta > 0, TipoCambio.fecha <= p.fecha)
        .order_by(TipoCambio.fecha.desc())
        .limit(1)
        .scalar_subquery()
    )
    porcentaje = cast(campo("porcentaje"), Numeric(9, 4))
    return (
        select(
            campo("origen").label("origen"),
            cast(campo("ref"), Integer).label("ref"),
            p.cantidad.label("unidades"),
            (p.cantidad * func.coalesce(p.costo_neto_usd, literal(0)) * porcentaje / 100).label("monto"),
            p.moneda.label("moneda"),
            # `tipo_cambio.venta` is a float: Numeric, so the amounts stay exact decimals.
            cast(func.coalesce(p.tipo_cambio, tasa), Numeric(18, 6)).label("tc"),
        )
        .select_from(p)
        .join(s, true())
        .where(p.tipo == "compra")
        .subquery("sell_ins_de_pasos")
    )


def _en(filas, moneda: ColumnElement) -> ColumnElement:
    """A row's amount in `moneda`: NULL (left out of a sum) when it needs a rate and has none."""
    return case(
        (filas.c.moneda == moneda, filas.c.monto),
        (moneda == "USD", filas.c.monto / filas.c.tc),
        else_=filas.c.monto * filas.c.tc,
    )


def _dialecto(db: Session) -> str:
    return db.get_bind().dialect.name


def por_bono(dialect: str) -> Select:
    """`(bono_id, unidades, monto)` per brand bonus some step got, the amount in the bonus's currency (unrounded)."""
    filas = _sell_ins(dialect)
    unidades = func.sum(filas.c.unidades)
    tope = SellInBonoMarca.tope_unidades
    return (
        select(
            SellInBonoMarca.id.label("bono_id"),
            case((and_(tope.isnot(None), unidades > tope), tope), else_=unidades).label("unidades"),
            func.sum(_en(filas, SellInBonoMarca.moneda)).label("monto"),
        )
        .join(filas, and_(filas.c.origen == BONO, filas.c.ref == SellInBonoMarca.id))
        .group_by(SellInBonoMarca.id, tope)
    )


def por_compra(dialect: str) -> Select:
    """`(compra_id, unidades, monto)` per Compras sell in some step got, the amount in the purchase's currency."""
    filas = _sell_ins(dialect)
    return (
        select(
            SellInCompra.id.label("compra_id"),
            func.sum(filas.c.unidades).label("unidades"),
            func.sum(_en(filas, SellInCompra.moneda)).label("monto"),
        )
        .join(filas, and_(filas.c.origen == COMPRA, filas.c.ref == SellInCompra.id))
        .group_by(SellInCompra.id)
    )


def _leer(db: Session, consulta: Select, columna, ids: Iterable[int]) -> dict[int, tuple[int, Decimal]]:
    ids = list(ids)
    if not ids:
        return {}
    return {
        ref: (int(unidades or 0), Decimal(str(monto or 0)))
        for ref, unidades, monto in db.execute(consulta.where(columna.in_(ids)))
    }


def de_bonos(db: Session, ids: Iterable[int]) -> dict[int, tuple[int, Decimal]]:
    """`{bono id: (units, amount in its currency)}`; a bonus no step got is left out."""
    return _leer(db, por_bono(_dialecto(db)), SellInBonoMarca.id, ids)


def de_compras(db: Session, ids: Iterable[int]) -> dict[int, tuple[int, Decimal]]:
    """`{sell_in_compras id: (units, amount in its currency)}`; a purchase no step got is left out."""
    return _leer(db, por_compra(_dialecto(db)), SellInCompra.id, ids)

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
- Units: a Compras sell in, the step's units. A brand bonus, the units its amount covered: the step's units x the %
  it got / the % it would get uncapped (its own or its model's %, or its amount per unit over the unit price; net of
  the product's VAT when it includes it; never over the purchase itself), so a cap (units or money) that ran out
  inside an invoice counts only the units it covered, and never more than its `tope_unidades`.

Both dialects: Postgres expands the JSONB list with `jsonb_array_elements`, SQLite (the router tests) with
`json_each`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from sqlalchemy import Integer, Numeric, Select, and_, case, cast, func, literal, literal_column, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.costo_si import CostoSiPaso
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoItem, SellInBonoMarca, SellInCompra
from app.services.costo_si.fuentes import sql_tc_factura

BONO = "bono"
COMPRA = "compra"


def _sell_ins(dialect: str):
    """One row per (purchase step, sell in it got): `origen`, `ref`, `item_id`, `unidades`, `porcentaje`, `precio` and
    `monto` (in the step's currency), `moneda` (the step's), `tc` (ARS per USD to change it)."""
    p = CostoSiPaso
    if dialect == "postgresql":
        s = func.jsonb_array_elements(p.sell_ins).table_valued("value").alias("s")

        def campo(clave: str) -> ColumnElement:
            return s.c.value.op("->>")(clave)

    else:
        s = func.json_each(p.sell_ins).table_valued("value").alias("s")

        def campo(clave: str) -> ColumnElement:
            return func.json_extract(s.c.value, f"$.{clave}")

    tabla = p.__tablename__
    tasa = literal_column(sql_tc_factura(f"{tabla}.ct_transaction", f"{tabla}.fecha"))
    porcentaje = cast(campo("porcentaje"), Numeric(9, 4))
    precio = func.coalesce(p.costo_neto_usd, literal(0))
    return (
        select(
            campo("origen").label("origen"),
            cast(campo("ref"), Integer).label("ref"),
            p.item_id.label("item_id"),
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
        .where(p.tipo == "compra")
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


def _dialecto(db: Session) -> str:
    return db.get_bind().dialect.name


def por_bono(dialect: str) -> Select:
    """`(bono_id, unidades, monto)` per brand bonus some step got, the amount in the bonus's currency (unrounded)."""
    filas = _sell_ins(dialect)
    unidades = func.sum(_unidades_de_bono(filas))
    tope = SellInBonoMarca.tope_unidades
    return (
        select(
            SellInBonoMarca.id.label("bono_id"),
            case((and_(tope.isnot(None), unidades > tope), tope), else_=unidades).label("unidades"),
            func.sum(_en(filas, SellInBonoMarca.moneda)).label("monto"),
        )
        .join(filas, and_(filas.c.origen == BONO, filas.c.ref == SellInBonoMarca.id))
        .outerjoin(
            SellInBonoItem,
            and_(SellInBonoItem.bono_id == SellInBonoMarca.id, SellInBonoItem.item_id == filas.c.item_id),
        )
        .outerjoin(ProductoERP, ProductoERP.item_id == filas.c.item_id)
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

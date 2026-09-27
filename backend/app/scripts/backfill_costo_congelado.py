"""Backfill frozen cost snapshots for sales that predate the frozen-cost
feature (backfill-costo-congelado-historico).

`costeo_service.congelar` (ml-ventas-modo-logistico PR3) only started
freezing `ml_order_item_costos` rows going forward. Every sale ingested
BEFORE that shipped has an item with no matching cost row, so its "Total
Gauss" bottom line cannot be computed. This script fills those holes --
and ONLY those holes; it never touches an item that already has a frozen
row (`INSERT ... ON CONFLICT DO NOTHING` is the structural backstop, on
top of the hole-only candidate query).

WHY history, never "the latest row" or the current ERP cost: a sale from
July costed with September's price is WRONG, and a wrong cost that reads
exactly like a right one is worse than a visibly missing one ("unknown is
not zero"). `agregar_metricas_ml.py::obtener_costo_item` is the existing
historical-cost resolver; its fallback #2 (latest history row regardless
of date) and #3 (current `ProductoERP.costo`) are EXACTLY what this script
must NOT do -- this script uses only its fallback #1: the most recent
`ItemCostListHistory` row (`coslis_id == 1`) dated AT OR BEFORE the order's
`date_created`. No such row -> the item is SKIPPED, nothing is written.

KNOWN APPROXIMATION, stated plainly rather than left for a reader to
assume otherwise: `tb_item_cost_list_history` carries no IVA rate, and
there is no IVA history table anywhere in this system. The CURRENT
`ProductoERP.iva` is the only source this script has, so `iva_pct` on a
backfilled row is NOT as historical as `costo_origen`/`costo_fecha` are.

FX for a USD-costed item uses the `TipoCambio` row in effect AT THE SALE
DATE (most recent `TipoCambio` row for USD with `fecha <= date_created`),
NEVER `latest_usd_rate_with_date` -- that resolves TODAY's rate and would
reintroduce the exact wrong-date bug this script exists to avoid.

Linkage reuses `costeo_service._productos_por_item` (the MLA ->
`PublicacionML` -> `ProductoERP.item_id` path, falling back to
`seller_sku` -> `ProductoERP.codigo`) UNCHANGED -- see that function's
docstring for why it resolves a whole batch in bulk instead of one query
per item. This script follows the same bulk discipline for cost-history
rows and FX rates: resolved once per batch, never once per item.

A backfilled row is tellable from a live-frozen one two ways: `fuente`
(`FUENTE_BACKFILL_PUBLICACION`/`FUENTE_BACKFILL_SKU`, never
`FUENTE_PUBLICACION`/`FUENTE_SKU`) and `costo_fecha` (set to the history
row's `iclh_cd`; a live-frozen row is always NULL there).

Run:
    python -m app.scripts.backfill_costo_congelado --limit 5000
    python -m app.scripts.backfill_costo_congelado --limit 5000 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from sqlalchemy import exists  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.item_cost_list_history import ItemCostListHistory  # noqa: E402
from app.models.ml_order_item_costo import MlOrderItemCosto  # noqa: E402
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps  # noqa: E402
from app.models.producto import ProductoERP  # noqa: E402
from app.models.tipo_cambio import TipoCambio  # noqa: E402
from app.services.ml_orders_ingestion.costeo_service import (  # noqa: E402
    FUENTE_BACKFILL_PUBLICACION,
    FUENTE_BACKFILL_COMBO,
    FUENTE_BACKFILL_SKU,
    FUENTE_PUBLICACION,
    FUENTE_SKU,
    _insert_stmt,
    _productos_por_item,
    componentes_por_combo,
)

logger = logging.getLogger(__name__)

# `_productos_por_item` maps FUENTE_PUBLICACION/FUENTE_SKU (the live-path
# constants) -- translate to this script's own backfill-only constants so
# a backfilled row is never mistaken for a live-frozen one.
_FUENTE_TRANSLATION = {
    FUENTE_PUBLICACION: FUENTE_BACKFILL_PUBLICACION,
    FUENTE_SKU: FUENTE_BACKFILL_SKU,
}

DEFAULT_BATCH_SIZE = 500
COSLIS_ID_PRINCIPAL = 1

SKIP_NO_LINKAGE = "no_linkage"
SKIP_NO_HISTORY = "no_dated_history_row"
# A history row that exists but carries 0 (or a negative) price is NOT a
# cost -- it is a hole in the ERP that happens to have a row. Freezing it
# would render the sale as 100% margin, and nothing downstream could tell
# that apart from a genuinely cheap product. `obtener_costo_item` already
# required `> 0` for exactly this reason; the same floor applies here.
SKIP_ZERO_COST = "history_row_price_is_zero"
# DISTINCT from SKIP_NO_HISTORY on purpose: there IS a dated history row,
# it just came without a price. "no cost for that date" and "the row is
# there but arrived empty" get fixed in DIFFERENT places in the ERP, and
# this breakdown is the only observable output the script has -- collapsing
# them into one counter makes it mute the first time it is not zero.
SKIP_NO_PRICE_IN_HISTORY = "history_row_has_no_price"
SKIP_NO_IVA = "no_iva"
SKIP_NO_FX = "no_fx_rate"
SKIP_NO_PRICE = "no_price"
SKIP_BAD_CURRENCY = "unrecognized_currency"
SKIP_NO_ORDER_DATE = "no_order_date"
SKIP_UNPARSEABLE = "unparseable_value"
# A pack/combo/kit whose composition IS known but at least one component
# has no real cost dated at or before the sale. Kept apart from
# `no_dated_history_row` because the fix is per COMPONENT -- loading a
# cost onto the combo itself would be the wrong move, and a counter that
# cannot tell them apart sends whoever reads it to the wrong place.
SKIP_COMBO_COMPONENT_NO_COST = "combo_component_no_cost"


@dataclass
class BackfillResult:
    examined: int = 0
    # TWO counters, not one, because they answer different questions and a
    # single `filled` answered neither honestly: it was incremented when an
    # item RESOLVED, before `ON CONFLICT DO NOTHING` had a say, and it moved
    # under `--dry-run` too. `resolved` is what we could cost; `written` is
    # what the database actually accepted.
    resolved: int = 0
    written: int = 0
    skipped: Counter = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.skipped is None:
            self.skipped = Counter()


def _candidate_query(db: Session):
    """Items in `ml_order_items_ops` with NO matching row in
    `ml_order_item_costos` on `(order_id, item_id, variation_id)`.

    `variation_id` is nullable on both sides -- `is_not_distinct_from`
    (NOT plain `==`, which never matches NULL) is what makes the
    no-variation case (the common one) count as a match instead of
    looking like a permanent hole.
    """
    hole_exists = exists().where(
        MlOrderItemCosto.order_id == MlOrderItemOps.order_id,
        MlOrderItemCosto.item_id == MlOrderItemOps.item_id,
        MlOrderItemCosto.variation_id.is_not_distinct_from(MlOrderItemOps.variation_id),
    )
    return (
        db.query(MlOrderItemOps, MlOrdersOps.date_created)
        .join(MlOrdersOps, MlOrdersOps.order_id == MlOrderItemOps.order_id)
        .filter(~hole_exists)
        .order_by(MlOrderItemOps.order_id, MlOrderItemOps.id)
    )


def _dated_history_rows(db: Session, item_ids: Sequence[int]) -> Dict[int, List[ItemCostListHistory]]:
    """All `coslis_id == 1` history rows for these ERP item ids, in ONE
    query for the whole batch -- never one query per item (bulk rule, same
    discipline `_productos_por_item` documents). Grouped by `item_id` and
    kept unsorted here; the per-item "most recent row dated at or before
    the sale" pick happens in `_pick_history_row`, in Python, off this
    already-fetched set."""
    if not item_ids:
        return {}
    rows = (
        db.query(ItemCostListHistory)
        .filter(
            ItemCostListHistory.coslis_id == COSLIS_ID_PRINCIPAL,
            ItemCostListHistory.item_id.in_(sorted(set(item_ids))),
        )
        .all()
    )
    by_item: Dict[int, List[ItemCostListHistory]] = {}
    for row in rows:
        by_item.setdefault(row.item_id, []).append(row)
    return by_item


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _tiene_precio(row: ItemCostListHistory) -> bool:
    """A history row that carries a real cost. A NULL or <= 0 `iclh_price`
    is a HOLE in the ERP, not a product that became free."""
    if row.iclh_price is None:
        return False
    try:
        return Decimal(str(row.iclh_price)) > 0
    except InvalidOperation:
        return False


def _pick_history_row(rows: Sequence[ItemCostListHistory], as_of: date) -> Optional[ItemCostListHistory]:
    """The most recent history row dated AT OR BEFORE `as_of` THAT CARRIES
    A REAL PRICE.

    Still no fallback to a later row and no fallback to `ProductoERP.costo`
    -- the sale is never costed with a figure from after it happened. What
    this DOES skip over is a priced-at-zero row, and that is not a loosening
    of the rule, it is the rule applied correctly: measured in production,
    4.360 zero rows spread over 4.353 products blocked 3.462 sales, because
    one junk row poisons every sale between itself and the next real cost.
    A zero is a MISSING cost, not a cost change, so the last real cost known
    before the sale is still the honest answer.

    Compared by DATE, not datetime: `iclh_cd` carries a time-of-day that "at
    the sale" was never meant to discriminate against."""
    fechadas = [row for row in rows if _as_date(row.iclh_cd) is not None and _as_date(row.iclh_cd) <= as_of]
    con_precio = [row for row in fechadas if _tiene_precio(row)]
    if not con_precio:
        return None
    return max(con_precio, key=lambda row: (_as_date(row.iclh_cd), row.iclh_id))


def _hay_fila_fechada(rows: Sequence[ItemCostListHistory], as_of: date) -> bool:
    """Whether ANY row is dated at or before `as_of`, priced or not. Only
    used to tell the two skip reasons apart: "the ERP has no cost for that
    date" and "every row it has for that date came empty" get fixed in
    different places."""
    return any(_as_date(row.iclh_cd) is not None and _as_date(row.iclh_cd) <= as_of for row in rows)


def _usd_rates_by_date(db: Session, dates: Sequence[date]) -> List[TipoCambio]:
    """Every USD `TipoCambio` row that could possibly be "the rate in
    effect" for any date in this batch, fetched ONCE. Covers from the
    earliest requested date back to the widest available row so the
    per-item pick in `_pick_fx_rate` (most recent row with
    `fecha <= sale date`) always has candidates without a second query."""
    if not dates:
        return []
    return (
        db.query(TipoCambio)
        .filter(TipoCambio.moneda == "USD", TipoCambio.fecha <= max(dates))
        .order_by(TipoCambio.fecha.asc(), TipoCambio.id.asc())
        .all()
    )


def _pick_fx_rate(rates: Sequence[TipoCambio], as_of: date) -> Optional[TipoCambio]:
    """The most recent USD `TipoCambio` row with `fecha <= as_of` -- the
    rate in effect AT THE SALE DATE, never today's `latest_usd_rate_with_date`
    (that would reintroduce the wrong-date bug this whole script exists to
    close)."""
    eligible = [rate for rate in rates if rate.fecha is not None and rate.venta and rate.fecha <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda rate: (rate.fecha, rate.id))


@dataclass(frozen=True)
class _EnArs:
    """One history row's cost expressed in ARS, with the rate that got it
    there (`None`/`None` when the row was already in ARS)."""

    valor: Decimal
    moneda: str
    tipo_cambio: Optional[Decimal]
    tipo_cambio_fecha: Optional[date]


def _a_ars(
    history_row: ItemCostListHistory,
    usd_rates: Sequence[TipoCambio],
    order_date: date,
) -> tuple[Optional[_EnArs], Optional[str]]:
    """`(_EnArs, None)` or `(None, <skip reason>)`. Shared by the direct
    path and the combo path so a component and a plain product are never
    converted by two different rules."""
    try:
        valor = Decimal(str(history_row.iclh_price))
    except InvalidOperation:
        return None, SKIP_UNPARSEABLE

    curr_id = history_row.curr_id
    if curr_id == 1:
        return _EnArs(valor, "ARS", None, None), None
    if curr_id != 2:
        return None, SKIP_BAD_CURRENCY

    rate_row = _pick_fx_rate(usd_rates, order_date)
    if rate_row is None:
        return None, SKIP_NO_FX
    try:
        tipo_cambio = Decimal(str(rate_row.venta))
    except InvalidOperation:
        return None, SKIP_UNPARSEABLE
    return _EnArs(valor * tipo_cambio, "USD", tipo_cambio, rate_row.fecha), None


def _resolver_combo(
    componentes: Sequence[tuple[int, Decimal]],
    history_by_item: Dict[int, List[ItemCostListHistory]],
    usd_rates: Sequence[TipoCambio],
    order_date: date,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The cost of a pack/combo/kit: the sum of its components, each at ITS
    own cost dated at or before the sale, times how many go in.

    ALL OR NOTHING. One component without a dated real cost means the whole
    combo is unknown -- a partial sum would read exactly like a complete
    one and understate the cost, which on this path means overstating the
    margin. Same rule the rest of this script follows: unknown is not zero.

    `costo_fecha` is the MOST RECENT component date, because that is when
    the combo's cost last changed. The earliest would claim the figure is
    older -- and therefore more settled -- than it is.
    """
    total = Decimal("0")
    fecha_mas_reciente: Optional[date] = None
    tipo_cambio: Optional[Decimal] = None
    tipo_cambio_fecha: Optional[date] = None

    for componente_id, qty in componentes:
        fila = _pick_history_row(history_by_item.get(componente_id, []), order_date)
        if fila is None:
            return None, SKIP_COMBO_COMPONENT_NO_COST
        en_ars, motivo = _a_ars(fila, usd_rates, order_date)
        if en_ars is None:
            return None, motivo
        total += en_ars.valor * qty
        fecha = _as_date(fila.iclh_cd)
        if fecha is not None and (fecha_mas_reciente is None or fecha > fecha_mas_reciente):
            fecha_mas_reciente = fecha
        if en_ars.tipo_cambio is not None:
            tipo_cambio = en_ars.tipo_cambio
            tipo_cambio_fecha = en_ars.tipo_cambio_fecha

    if total <= 0:
        return None, SKIP_COMBO_COMPONENT_NO_COST

    return (
        {
            # Already summed IN ARS: a combo can mix an ARS component with
            # a USD one, so there is no single source currency to report.
            "costo_origen": total,
            "moneda": "ARS",
            "tipo_cambio": tipo_cambio,
            "tipo_cambio_fecha": tipo_cambio_fecha,
            "costo_unitario_ars": total,
            "costo_fecha": fecha_mas_reciente,
        },
        None,
    )


def _resolve_backfill_cost(
    producto: ProductoERP,
    fuente_live: str,
    history_rows: Sequence[ItemCostListHistory],
    componentes: Sequence[tuple[int, Decimal]],
    history_by_item: Dict[int, List[ItemCostListHistory]],
    usd_rates: Sequence[TipoCambio],
    order_date: date,
    result: BackfillResult,
) -> Optional[Dict[str, Any]]:
    """One item's frozen snapshot, by whichever of TWO paths applies.

    The product's OWN dated cost comes first. Only when that is missing
    does the combo path run, and only for a product the ERP knows the
    composition of -- a pack has no purchase cost because nobody buys a
    pack, so its zero-priced history is a consequence of what it is, not a
    hole to be filled by hand.

    Order matters and is deliberate: a product that has a real cost of its
    own is costed with it, even if it also happens to have components.
    Summing components for something the ERP actually prices would replace
    a measured figure with a derived one.
    """
    if producto.iva is None:
        result.skipped[SKIP_NO_IVA] += 1
        return None
    try:
        iva_pct = Decimal(str(producto.iva))
    except InvalidOperation:
        result.skipped[SKIP_UNPARSEABLE] += 1
        return None

    history_row = _pick_history_row(history_rows, order_date)

    if history_row is None:
        if componentes:
            resuelto, motivo = _resolver_combo(componentes, history_by_item, usd_rates, order_date)
            if resuelto is None:
                result.skipped[motivo or SKIP_COMBO_COMPONENT_NO_COST] += 1
                return None
            resuelto["iva_pct"] = iva_pct
            resuelto["fuente"] = FUENTE_BACKFILL_COMBO
            resuelto["producto_item_id"] = producto.item_id
            return resuelto

        # Two different problems, kept apart because they get fixed in
        # different places: the ERP has NO row for that date at all, or it
        # has rows and every one of them came without a price. The second
        # is the case the ERP can close by loading a cost.
        if _hay_fila_fechada(history_rows, order_date):
            result.skipped[SKIP_NO_PRICE_IN_HISTORY] += 1
        else:
            result.skipped[SKIP_NO_HISTORY] += 1
        return None

    try:
        costo_origen = Decimal(str(history_row.iclh_price))
    except InvalidOperation:
        result.skipped[SKIP_UNPARSEABLE] += 1
        return None

    if costo_origen <= 0:
        # Unreachable by construction: `_pick_history_row` only ever
        # returns a row `_tiene_precio` accepted. Kept as a backstop so a
        # future change to the picker cannot silently freeze a zero and
        # declare the sale 100% margin.
        result.skipped[SKIP_ZERO_COST] += 1
        return None

    en_ars, motivo = _a_ars(history_row, usd_rates, order_date)
    if en_ars is None:
        result.skipped[motivo or SKIP_UNPARSEABLE] += 1
        return None

    return {
        "costo_origen": costo_origen,
        "moneda": en_ars.moneda,
        "tipo_cambio": en_ars.tipo_cambio,
        "tipo_cambio_fecha": en_ars.tipo_cambio_fecha,
        "costo_unitario_ars": en_ars.valor,
        "iva_pct": iva_pct,
        "costo_fecha": _as_date(history_row.iclh_cd),
        "fuente": _FUENTE_TRANSLATION[fuente_live],
        "producto_item_id": producto.item_id,
    }


def run_backfill(limit: Optional[int], dry_run: bool, batch_size: int = DEFAULT_BATCH_SIZE) -> BackfillResult:
    result = BackfillResult()
    db = SessionLocal()
    try:
        consulta = _candidate_query(db)
        if limit is not None:
            consulta = consulta.limit(limit)
        rows = consulta.all()
        result.examined = len(rows)
        if not rows:
            return result

        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            items = [row[0] for row in batch]
            order_dates = {row[0].order_id: row[1] for row in batch}

            # Bulk product linkage (reused UNCHANGED from costeo_service --
            # see its docstring for why this is 3 queries for the whole
            # batch instead of up to 3 per item).
            productos_por_indice = _productos_por_item(db, items)

            # Bulk history + FX lookups for this batch only.
            item_ids_needed = [producto.item_id for producto, _ in productos_por_indice.values()]

            # Composition for the whole batch in ONE query, and the
            # components' ids folded into the SAME history fetch -- a
            # second round-trip per combo would reintroduce exactly the
            # N+1 this module spends a docstring forbidding.
            combos = componentes_por_combo(db, item_ids_needed)
            for componentes in combos.values():
                item_ids_needed.extend(componente_id for componente_id, _ in componentes)

            history_by_item = _dated_history_rows(db, item_ids_needed)
            dates_needed = [_as_date(d) for d in order_dates.values() if d is not None]
            usd_rates = _usd_rates_by_date(db, dates_needed)

            values_to_insert: List[Dict[str, Any]] = []

            for idx, item in enumerate(items):
                order_date_dt = order_dates.get(item.order_id)
                if order_date_dt is None:
                    result.skipped[SKIP_NO_ORDER_DATE] += 1
                    continue
                order_date = _as_date(order_date_dt)

                if item.unit_price is None:
                    result.skipped[SKIP_NO_PRICE] += 1
                    continue

                resuelto = productos_por_indice.get(idx)
                if resuelto is None:
                    result.skipped[SKIP_NO_LINKAGE] += 1
                    continue
                producto, fuente_live = resuelto

                history_rows = history_by_item.get(producto.item_id, [])
                resolved = _resolve_backfill_cost(
                    producto,
                    fuente_live,
                    history_rows,
                    combos.get(producto.item_id, []),
                    history_by_item,
                    usd_rates,
                    order_date,
                    result,
                )
                if resolved is None:
                    continue

                try:
                    precio_unitario = Decimal(str(item.unit_price))
                except InvalidOperation:
                    result.skipped[SKIP_UNPARSEABLE] += 1
                    continue

                values_to_insert.append(
                    {
                        "order_id": item.order_id,
                        "item_id": item.item_id,
                        "variation_id": item.variation_id,
                        "costo_origen": resolved["costo_origen"],
                        "moneda": resolved["moneda"],
                        "tipo_cambio": resolved["tipo_cambio"],
                        "tipo_cambio_fecha": resolved["tipo_cambio_fecha"],
                        "costo_unitario_ars": resolved["costo_unitario_ars"],
                        "iva_pct": resolved["iva_pct"],
                        "precio_unitario": precio_unitario,
                        "costo_fecha": resolved["costo_fecha"],
                        "fuente": resolved["fuente"],
                        "producto_item_id": resolved["producto_item_id"],
                    }
                )
                result.resolved += 1

            if dry_run or not values_to_insert:
                continue

            # ONE round-trip for the whole batch, not one per row. This
            # module preaches bulk discipline in its own docstring; a
            # row-at-a-time loop under that docstring is 70k round-trips.
            # `.values(<list>)` is ONE multi-VALUES statement, so the
            # RETURNING rows below come straight from that statement rather
            # than from SQLAlchemy's insertmanyvalues batching. The
            # executemany form (`execute(stmt, <list>)`) also counts
            # correctly under the conflict test here -- this is the plainer
            # of two working shapes, not a fix for a measured defect.
            stmt = _insert_stmt(db, MlOrderItemCosto.__table__).values(values_to_insert)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["order_id", "item_id", "variation_id"],
            )
            # `RETURNING` yields one row per row the INSERT actually
            # accepted, so `ON CONFLICT DO NOTHING` dropping a row simply
            # does not appear here. This statement's own result, never a
            # table-wide COUNT(*) taken before and after: the ONLY scenario
            # that can make this differ from `len(values_to_insert)` is a
            # concurrent writer, and under a concurrent writer a global
            # count attributes THAT session's rows to this run. The counter
            # written to stop lying would have lied in exactly the case it
            # existed for.
            inserted = db.execute(stmt.returning(MlOrderItemCosto.id))
            result.written += len(inserted.fetchall())
            db.commit()

        return result
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill ml_order_item_costos for sales ingested before the "
        "frozen-cost feature shipped, from dated ERP cost HISTORY only -- never "
        "from the current cost."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after examining this many candidate items. WITHOUT it the "
        "run covers every candidate, which is what a backfill is for -- a "
        "default cap re-examines the same unresolvable items every run and "
        "starves the tail (observed in production: `examined` stayed pinned "
        "at the cap while `resolved` fell to near zero).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Commit batch size (default {DEFAULT_BATCH_SIZE}). Products/history/FX are resolved "
        "in bulk per batch, never per item.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and report what WOULD be filled/skipped; write nothing.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)

    result = run_backfill(limit=args.limit, dry_run=args.dry_run, batch_size=args.batch_size)

    skipped_total = sum(result.skipped.values())
    logger.info(
        "backfill_costo_congelado: complete (dry_run=%s, limit=%s) -- "
        "examined=%s resolved=%s written=%s skipped_total=%s skipped_breakdown=%s",
        args.dry_run,
        args.limit,
        result.examined,
        result.resolved,
        result.written,
        skipped_total,
        dict(result.skipped),
    )


if __name__ == "__main__":
    main()

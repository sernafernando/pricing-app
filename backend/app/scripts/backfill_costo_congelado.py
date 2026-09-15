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
    FUENTE_BACKFILL_SKU,
    FUENTE_PUBLICACION,
    FUENTE_SKU,
    _insert_stmt,
    _productos_por_item,
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
SKIP_ZERO_COST = "history_row_has_no_price"
SKIP_NO_IVA = "no_iva"
SKIP_NO_FX = "no_fx_rate"
SKIP_NO_PRICE = "no_price"
SKIP_BAD_CURRENCY = "unrecognized_currency"
SKIP_NO_ORDER_DATE = "no_order_date"
SKIP_UNPARSEABLE = "unparseable_value"


@dataclass
class BackfillResult:
    examined: int = 0
    filled: int = 0
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


def _pick_history_row(rows: Sequence[ItemCostListHistory], as_of: date) -> Optional[ItemCostListHistory]:
    """The most recent history row dated AT OR BEFORE `as_of`. No fallback
    to a later row and no fallback to `ProductoERP.costo` -- a miss here
    means the item is SKIPPED, never costed some other way. Compared by
    DATE, not datetime: `iclh_cd` carries a time-of-day that "at the sale"
    was never meant to discriminate against."""
    eligible = [row for row in rows if _as_date(row.iclh_cd) is not None and _as_date(row.iclh_cd) <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (_as_date(row.iclh_cd), row.iclh_id))


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


def _resolve_backfill_cost(
    producto: ProductoERP,
    fuente_live: str,
    history_rows: Sequence[ItemCostListHistory],
    usd_rates: Sequence[TipoCambio],
    order_date: date,
    result: BackfillResult,
) -> Optional[Dict[str, Any]]:
    history_row = _pick_history_row(history_rows, order_date)
    if history_row is None:
        result.skipped[SKIP_NO_HISTORY] += 1
        return None

    if producto.iva is None:
        result.skipped[SKIP_NO_IVA] += 1
        return None

    if history_row.iclh_price is None:
        result.skipped[SKIP_NO_HISTORY] += 1
        return None

    try:
        costo_origen = Decimal(str(history_row.iclh_price))
        iva_pct = Decimal(str(producto.iva))
    except InvalidOperation:
        result.skipped[SKIP_UNPARSEABLE] += 1
        return None

    if costo_origen <= 0:
        # See SKIP_ZERO_COST: a row with no price is an ERP hole, not a
        # free product. Skipping leaves the sale visibly uncosted, which a
        # reader can act on; freezing 0 would silently claim full margin.
        result.skipped[SKIP_ZERO_COST] += 1
        return None

    curr_id = history_row.curr_id
    if curr_id == 1:
        moneda = "ARS"
        tipo_cambio = None
        tipo_cambio_fecha = None
        costo_unitario_ars = costo_origen
    elif curr_id == 2:
        moneda = "USD"
        rate_row = _pick_fx_rate(usd_rates, order_date)
        if rate_row is None:
            result.skipped[SKIP_NO_FX] += 1
            return None
        try:
            tipo_cambio = Decimal(str(rate_row.venta))
        except InvalidOperation:
            result.skipped[SKIP_UNPARSEABLE] += 1
            return None
        tipo_cambio_fecha = rate_row.fecha
        costo_unitario_ars = costo_origen * tipo_cambio
    else:
        result.skipped[SKIP_BAD_CURRENCY] += 1
        return None

    costo_fecha = _as_date(history_row.iclh_cd)

    return {
        "costo_origen": costo_origen,
        "moneda": moneda,
        "tipo_cambio": tipo_cambio,
        "tipo_cambio_fecha": tipo_cambio_fecha,
        "costo_unitario_ars": costo_unitario_ars,
        "iva_pct": iva_pct,
        "costo_fecha": costo_fecha,
        "fuente": _FUENTE_TRANSLATION[fuente_live],
        "producto_item_id": producto.item_id,
    }


def run_backfill(limit: int, dry_run: bool, batch_size: int = DEFAULT_BATCH_SIZE) -> BackfillResult:
    result = BackfillResult()
    db = SessionLocal()
    try:
        rows = _candidate_query(db).limit(limit).all()
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
                resolved = _resolve_backfill_cost(producto, fuente_live, history_rows, usd_rates, order_date, result)
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
                result.filled += 1

            if dry_run or not values_to_insert:
                continue

            for values in values_to_insert:
                stmt = _insert_stmt(db, MlOrderItemCosto.__table__).values(**values)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["order_id", "item_id", "variation_id"],
                )
                db.execute(stmt)
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
    parser.add_argument("--limit", type=int, default=5000, help="Max candidate items examined in this run.")
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
        "examined=%s filled=%s skipped_total=%s skipped_breakdown=%s",
        args.dry_run,
        args.limit,
        result.examined,
        result.filled,
        skipped_total,
        dict(result.skipped),
    )


if __name__ == "__main__":
    main()

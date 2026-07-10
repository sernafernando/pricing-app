"""
Script for adding TP-Link sales metrics (store 2645, coslis_id=8) — BACKFILL.

Slice 2 (SDD change tplink-metricas-dual-key-dedup, design v2 D1/D5): this
job is now a THIN WRAPPER around the shared per-order aggregation core
(`app.scripts._tplink_metricas_core`). It only owns:
  - the CLI date-range -> half-open `[from_ts, to_ts)` window computation
    (`compute_date_window`), and
  - the DB session lifecycle / batching / commit cadence.

All aggregation (SQL query shape, per-order SUM-fold, upsert payload
mapping, and the actual insert/update) is delegated to the core module so
the backfill and incremental jobs can never drift (design D1/D4).

Backfill invocation:
    python app/scripts/agregar_metricas_tplink.py --from-date 2026-01-01 --to-date <today>
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import argparse
from datetime import datetime, date, timedelta
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.producto import ProductoERP
from app.scripts._tplink_metricas_core import (
    TPLINK_COSLIS_ID,
    TPLINK_STORE_ID,
    build_aggregation_sql,
    build_upsert_payload,
    fold_order_rows,
    upsert_metrica,
)

# Module-level constants — kept identical to the shared core for readability
# at call sites in this file.
_TPLINK_STORE_ID: int = TPLINK_STORE_ID
_TPLINK_COSLIS_ID: int = TPLINK_COSLIS_ID

# Missing-cost tracking, retained from the pre-slice-2 per-detail flow for
# `obtener_costo_item()` callers/tests. The main aggregation path (SQL) now
# does its own coslis_id=8-only cost lookup with the same "never fall back
# to list 1" guarantee (see `_tplink_metricas_core.build_aggregation_sql`).
_missing_cost_count: int = 0
_missing_cost_sample: list = []
_MISSING_COST_SAMPLE_CAP = 20


def obtener_costo_item(
    db: Session, item_id: int, fecha_venta: datetime, cantidad: float, mlo_id: int
) -> tuple[float, str]:
    """
    Obtains item cost from ERP cost list 8 (TPLINK_COSLIS_ID).

    Priority:
    1. Cost history (item_cost_list_history, coslis_id=8) before or on sale date.
    2. Current cost from history (coslis_id=8, no date filter).
    3. Product cost fallback (productos_erp.costo).

    NEVER falls back to coslis_id=1. Missing-cost counter incremented when
    no list-8 cost is found and costo=0 is returned.

    Retained as a standalone utility (not called by the main aggregation
    flow, which does this lookup in SQL — see `build_aggregation_sql`) for
    callers that need a single-item cost lookup outside the aggregating
    query, and for its existing regression test coverage.

    Returns:
        (costo_total_sin_iva, moneda)
    """
    global _missing_cost_count, _missing_cost_sample

    # 1. Cost history before or on sale date (coslis_id=8)
    cost_history = (
        db.query(ItemCostListHistory)
        .filter(
            and_(
                ItemCostListHistory.item_id == item_id,
                ItemCostListHistory.coslis_id == _TPLINK_COSLIS_ID,
                ItemCostListHistory.iclh_cd <= fecha_venta,
            )
        )
        .order_by(desc(ItemCostListHistory.iclh_cd))
        .first()
    )

    if cost_history and cost_history.iclh_price and float(cost_history.iclh_price) > 0:
        costo_unitario = float(cost_history.iclh_price)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if cost_history.curr_id == 2 else "ARS"
        return (costo_total, moneda)

    # 2. Fallback: current most-recent cost from history (coslis_id=8)
    cost_actual = (
        db.query(ItemCostListHistory)
        .filter(and_(ItemCostListHistory.item_id == item_id, ItemCostListHistory.coslis_id == _TPLINK_COSLIS_ID))
        .order_by(desc(ItemCostListHistory.iclh_cd))
        .first()
    )

    if cost_actual and cost_actual.iclh_price and float(cost_actual.iclh_price) > 0:
        costo_unitario = float(cost_actual.iclh_price)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if cost_actual.curr_id == 2 else "ARS"
        return (costo_total, moneda)

    # 3. Last fallback: product cost (productos_erp.costo)
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

    if producto and producto.costo and float(producto.costo) > 0:
        costo_unitario = float(producto.costo)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if producto.moneda_costo and producto.moneda_costo.value == "USD" else "ARS"
        return (costo_total, moneda)

    # No list-8 cost found — log and return 0
    _missing_cost_count += 1
    if len(_missing_cost_sample) < _MISSING_COST_SAMPLE_CAP:
        _missing_cost_sample.append(item_id)

    return (0.0, "ARS")


def compute_date_window(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """
    Computes the half-open `[from_ts, to_ts)` window for the shared
    aggregating query (design D3), from CLI `--from-date`/`--to-date`
    (inclusive calendar dates).

    `from_ts` = `from_date` at midnight. `to_ts` = `to_date + 1 day` at
    midnight, so orders on `to_date` (at any time of day) are included and
    nothing on `to_date + 1` is double-counted.
    """
    from_ts = datetime.combine(from_date, datetime.min.time())
    to_ts = datetime.combine(to_date + timedelta(days=1), datetime.min.time())
    return from_ts, to_ts


def agregar_metricas_rango(from_date: date, to_date: date, batch_size: int = 100) -> None:
    """Adds/updates metrics for a date range via the shared aggregation core."""
    db = SessionLocal()

    try:
        print(f"\n{'=' * 60}")
        print("AGREGACION DE METRICAS TP-LINK (store 2645, coslis_id=8)")
        print(f"{'=' * 60}")

        from_ts, to_ts = compute_date_window(from_date, to_date)
        print(f"Rango: {from_date} a {to_date} (inclusive)")
        print(f"Query: {from_ts} <= fecha_venta < {to_ts}")
        print()

        result = db.execute(
            build_aggregation_sql(),
            {
                "from_ts": from_ts,
                "to_ts": to_ts,
                "coslis_id": _TPLINK_COSLIS_ID,
                "store_id": _TPLINK_STORE_ID,
            },
        )
        rows = result.fetchall()
        print(f"Detalles obtenidos: {len(rows)}")

        folded = fold_order_rows(rows, db_session=db)
        print(f"Ordenes (post-fold): {len(folded)}")
        print()

        total_insertados = 0
        total_actualizados = 0
        total_errores = 0
        procesados = 0

        for order_id, folded_row in folded.items():
            try:
                payload = build_upsert_payload(folded_row)
                resultado = upsert_metrica(db, payload)
                if resultado == "insertado":
                    total_insertados += 1
                else:
                    total_actualizados += 1
            except Exception as e:
                total_errores += 1
                print(f"  Error procesando orden {order_id}: {str(e)}")
                db.rollback()
                continue

            procesados += 1
            if procesados % batch_size == 0:
                try:
                    db.commit()
                except Exception as e:
                    print(f"  Error commit lote (orden {order_id}): {str(e)}")
                    db.rollback()
                print(
                    f"  Procesados: {procesados} | Nuevos: {total_insertados} | Actualizados: {total_actualizados}"
                )

        try:
            db.commit()
        except Exception as e:
            print(f"  Error commit final: {str(e)}")
            db.rollback()

        print()
        print(f"{'=' * 60}")
        print("COMPLETADO")
        print(f"{'=' * 60}")
        print(f"Insertados: {total_insertados}")
        print(f"Actualizados: {total_actualizados}")
        print(f"Errores: {total_errores}")

    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agregar metricas TP-Link (store 2645, coslis_id=8)")
    parser.add_argument("--from-date", required=True, help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--to-date", default=None, help="Fecha fin YYYY-MM-DD (default: hoy)")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    from_date = datetime.strptime(args.from_date, "%Y-%m-%d").date()
    to_date = datetime.strptime(args.to_date, "%Y-%m-%d").date() if args.to_date else date.today()

    agregar_metricas_rango(from_date, to_date, args.batch_size)


if __name__ == "__main__":
    main()

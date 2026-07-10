"""
Script for adding TP-Link sales metrics (store 2645, coslis_id=8) — INCREMENTAL.
Incremental version that processes the last 10 minutes of data.
Designed to run every 5 minutes via cron.

Slice 2 (SDD change tplink-metricas-dual-key-dedup, design v2 D1/D3): this
job is now a THIN WRAPPER around the shared per-order aggregation core
(`app.scripts._tplink_metricas_core`), the SAME core the backfill job uses.
It only owns:
  - the last-10-minutes window computation (`compute_date_window`), and
  - the DB session lifecycle / batching / commit cadence.

The old `DISTINCT ON (tmlod.mlo_id)` per-detail-collapsing query has been
REMOVED — the shared core's aggregating query + Python SUM-fold replaces it,
so multi-item orders are correctly summed instead of arbitrarily collapsed
to one detail (design D1).

Side effects deliberately NOT included vs ML incremental:
The three ML global side-effect helpers (offset consumo grupo, offset
consumo individual, and markup notification) are excluded because the ML
incremental already runs them for store-2645 orders. Including them here
would double-count offset consumo and duplicate markup notifications.

Cron (mirror ML's 5-min cadence):
    */5 * * * * cd /var/www/html/pricing-app/backend && \\
        /var/www/html/pricing-app/backend/venv/bin/python \\
        app/scripts/agregar_metricas_tplink_incremental.py \\
        >> /var/log/pricing-app/tplink_metricas_incremental.log 2>&1
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
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

# Mirrors ML incremental's window width — kept as a named constant.
_WINDOW_MINUTES: int = 10


def compute_date_window(now: datetime) -> tuple[datetime, datetime]:
    """
    Computes the half-open `[from_ts, to_ts)` window for the last
    `_WINDOW_MINUTES` minutes, ending at `now`.
    """
    from_ts = now - timedelta(minutes=_WINDOW_MINUTES)
    to_ts = now
    return from_ts, to_ts


def calcular_metricas_locales(db: Session, from_ts: datetime, to_ts: datetime):
    """
    Runs the shared aggregating query for the `[from_ts, to_ts)` window and
    returns the raw per-detail rows (NOT yet folded — folding happens in
    `process_and_insert` via `fold_order_rows`).
    """
    print("\nConsultando tablas locales PostgreSQL (TP-Link)...")
    print(f"   Rango: {from_ts} a {to_ts}")

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
    print(f"  Obtenidos {len(rows)} detalles (store {_TPLINK_STORE_ID}, coslis_id={_TPLINK_COSLIS_ID})")

    return rows


def process_and_insert(db: Session, rows) -> tuple[int, int, int]:
    """
    Folds the per-detail `rows` into per-order rows (shared core), then
    upserts each folded order into `tplink_ventas_metricas` via the shared
    `build_upsert_payload`/`upsert_metrica` helpers.

    Side effects deliberately NOT included vs ML incremental (see module
    docstring): no offset-consumo / markup-notification side effects.
    """
    if not rows:
        print("  No hay datos para procesar")
        return 0, 0, 0

    print(f"\nProcesando {len(rows)} detalles (TP-Link)...")

    folded = fold_order_rows(rows, db_session=db)
    print(f"  Ordenes (post-fold): {len(folded)}")

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
            print(f"  Error procesando operacion {order_id}: {str(e)}")
            db.rollback()
            continue

        procesados += 1
        if procesados % 100 == 0:
            db.commit()
            print(f"  Progreso: {procesados}/{len(folded)}")

    db.commit()

    return total_insertados, total_actualizados, total_errores


def main() -> None:
    # INCREMENTAL: process last 10 minutes (mirror ML incremental window)
    now = datetime.now()
    from_ts, to_ts = compute_date_window(now)

    print("=" * 60)
    print(f"METRICAS TP-LINK INCREMENTAL (store {_TPLINK_STORE_ID}, coslis_id={_TPLINK_COSLIS_ID})")
    print("=" * 60)
    print(f"Ejecutado: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Rango: {from_ts.strftime('%Y-%m-%d %H:%M:%S')} a {to_ts.strftime('%Y-%m-%d %H:%M:%S')}")

    db = SessionLocal()

    try:
        rows = calcular_metricas_locales(db, from_ts, to_ts)
        insertados, actualizados, errores = process_and_insert(db, rows)

        print("\n" + "=" * 60)
        print("COMPLETADO")
        print("=" * 60)
        print(f"Insertados: {insertados}")
        print(f"Actualizados: {actualizados}")
        print(f"Errores: {errores}")
        print()

    except Exception as e:
        print(f"\nError critico: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

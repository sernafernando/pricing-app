"""The single writer of Gauss metrics (design D7). `recompute_order_metrics`
absorbs `persistir_total_gauss`'s write side: upserts `ml_order_metrics` +
`ml_venta_deducciones` + the legacy `ml_orders_ops.total_gauss*` sort-key
columns (design D1: kept until a later cleanup PR). NEVER commits -- the
caller controls the transaction, exactly like `persistir_total_gauss` did.

`ml_order_metrics`/`ml_venta_deducciones` are written with a real
`INSERT ... ON CONFLICT DO UPDATE` (post-PR1 review fix), not a
read-then-`db.add`: two callers legitimately recompute the SAME order
concurrently with no existing row yet (the background sweep alongside a
per-order write on ingestion), and a read-then-decide race lets the SECOND
caller's flush hit the primary key and raise `IntegrityError`, aborting
that caller's whole batch. The upsert makes the second writer update
instead of crash -- whichever commits last simply wins, same as any other
last-write-wins column this function already owns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Sequence

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.services.ml_ventas_desglose.deducciones import DEDUCCIONES
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.types import GaussStatus, OrderMetrics


def _insert(db: Session, table):
    """Dialect-aware `INSERT` builder for the upserts below. Production
    runs PostgreSQL; the test suite runs SQLite (only `@pytest.mark.postgres`
    tests use a real Postgres connection) -- both support
    `ON CONFLICT DO UPDATE`, but `postgresql.insert`/`sqlite.insert` are
    different classes with the same `.on_conflict_do_update(...)` shape."""
    if db.get_bind().dialect.name == "postgresql":
        return postgresql.insert(table)
    return sqlite.insert(table)


def recompute_order_metrics(db: Session, order_ids: Sequence[int]) -> Dict[int, OrderMetrics]:
    """Computes (via `compute.compute_order_metrics`, the single producer)
    and upserts `order_ids`' metrics. Returns the same `OrderMetrics` it
    stored, so a caller (e.g. `persistir_total_gauss`) never needs a second
    read to report what it just wrote."""
    order_ids = list(order_ids)
    if not order_ids:
        return {}

    metrics_by_order = compute_order_metrics(db, order_ids)
    if not metrics_by_order:
        return metrics_by_order

    orders = db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_(order_ids)).all()
    orders_by_id = {o.order_id: o for o in orders}

    # Still read first -- but only to know which `ml_venta_deducciones` rows
    # a deduction that stopped applying must delete, never to decide insert
    # vs. update (that decision is now the database's, via ON CONFLICT).
    existing_deducciones = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id.in_(order_ids)).all()
    existing_by_key = {(row.order_id, row.code): row for row in existing_deducciones}

    orden_by_code = {d.code: d.orden for d in DEDUCCIONES}

    now = datetime.now(timezone.utc)

    metrics_rows: list[dict] = []
    deduccion_rows: list[dict] = []
    delete_ids: list[int] = []

    for order_id, metrics in metrics_by_order.items():
        order = orders_by_id.get(order_id)
        if order is not None:
            order.total_gauss = metrics.total_gauss
            order.total_gauss_at = now
            order.total_gauss_stale = False
            order.total_gauss_provisional = metrics.gauss_status == GaussStatus.PROVISIONAL

        metrics_rows.append(
            {
                "order_id": order_id,
                "neto": metrics.neto,
                "neto_sin_iva": metrics.neto_sin_iva,
                "iva_reconcilia": metrics.iva_reconcilia,
                "costo_mercaderia": metrics.costo_mercaderia,
                "total_gauss": metrics.total_gauss,
                "markup_pct": metrics.markup_pct,
                "gauss_status": metrics.gauss_status.value,
                "provisional_falta": metrics.provisional_falta,
                "unresolved_reason": metrics.unresolved_reason,
                "formula_version": metrics.formula_version,
                "computed_at": metrics.computed_at,
            }
        )

        for code, monto, _concepto in metrics.lineas:
            deduccion_rows.append({"order_id": order_id, "code": code, "orden": orden_by_code[code], "monto": monto})

        # A deduction that stopped applying loses its row (persistir_total_
        # gauss's own rule, deducciones.py ~685-698) -- never left carrying a
        # freight/percent amount that is no longer owed.
        vigentes = {code for code, _monto, _concepto in metrics.lineas}
        for (row_order_id, code), deduccion_row in existing_by_key.items():
            if row_order_id == order_id and code not in vigentes:
                delete_ids.append(deduccion_row.id)

    # Sorted by key before the upsert: two workers recomputing overlapping
    # batches (PR2+) then take row locks in the same order, so they queue
    # instead of deadlocking.
    metrics_rows.sort(key=lambda row: row["order_id"])
    deduccion_rows.sort(key=lambda row: (row["order_id"], row["code"]))

    metrics_stmt = _insert(db, MlOrderMetrics.__table__).values(metrics_rows)
    metrics_update_cols = {col: metrics_stmt.excluded[col] for col in metrics_rows[0] if col != "order_id"}
    db.execute(metrics_stmt.on_conflict_do_update(index_elements=["order_id"], set_=metrics_update_cols))

    if deduccion_rows:
        deduccion_stmt = _insert(db, MlVentaDeduccion.__table__).values(deduccion_rows)
        db.execute(
            deduccion_stmt.on_conflict_do_update(
                index_elements=["order_id", "code"],
                set_={"orden": deduccion_stmt.excluded["orden"], "monto": deduccion_stmt.excluded["monto"]},
            )
        )

    if delete_ids:
        db.query(MlVentaDeduccion).filter(MlVentaDeduccion.id.in_(delete_ids)).delete(synchronize_session=False)

    return metrics_by_order

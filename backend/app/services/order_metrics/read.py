"""Reader path over already-stored Gauss metrics (design D2/D13, PR7).

This is the mirror of `store.recompute_order_metrics`'s write side: it
NEVER recomputes anything, only reads `ml_order_metrics` +
`ml_venta_deducciones` (the chain lines, design D2 "Chain lines stay in
`ml_venta_deducciones`, written by the same recompute"). Callers switching
away from the live `compute_order_metrics`/`calcular_total_gauss` chain
(spec `ml-order-stored-metrics` R5) use this module instead.

`_CONCEPTO_BY_CODE` reconstructs the static per-code label from the
`DEDUCCIONES` registry. One known, documented loss of fidelity: the Flex
freight line's PER-ORDER concept (the actual logistics company name,
resolved live at compute time -- `deducciones.py` `EnvioFlexDeduccion`) is
never persisted onto `ml_venta_deducciones`, only its `monto`. Reading it
back here therefore falls back to the resolver's STATIC concept ("Envío
Flex (costo propio)") instead of the per-order courier name. Storing that
per-order label is out of this PR's scope (`ml_venta_deducciones`'s columns
are frozen by PR1/PR5's migration-immutability contract); this is a known,
accepted regression in display fidelity, not a bug.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from sqlalchemy.orm import Session

from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.services.ml_ventas_desglose.deducciones import DEDUCCIONES
from app.services.order_metrics.queue import POISON_THRESHOLD
from app.services.order_metrics.types import GaussStatus, OrderMetrics

_CONCEPTO_BY_CODE: Dict[str, str] = {deduccion.code: deduccion.concepto for deduccion in DEDUCCIONES}


def read_stored_metrics(db: Session, order_ids: Sequence[int]) -> Dict[int, OrderMetrics]:
    """Bulk read of the last-stored `OrderMetrics` for every `order_id` that
    HAS a `ml_order_metrics` row. An `order_id` with no stored row is simply
    ABSENT from the result -- never a fabricated/zero entry; the `pending`
    state (`metrics_state_for_orders`) is what tells a caller why. Two bulk
    queries total, regardless of how many order_ids are passed -- never one
    query per order."""
    order_ids = list(order_ids)
    result: Dict[int, OrderMetrics] = {}
    if not order_ids:
        return result

    rows = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id.in_(order_ids)).all()
    if not rows:
        return result
    found_ids = [row.order_id for row in rows]

    deduccion_rows = (
        db.query(MlVentaDeduccion)
        .filter(MlVentaDeduccion.order_id.in_(found_ids))
        .order_by(MlVentaDeduccion.order_id, MlVentaDeduccion.orden)
        .all()
    )
    lineas_by_order: Dict[int, List] = {}
    for deduccion in deduccion_rows:
        concepto = _CONCEPTO_BY_CODE.get(deduccion.code)
        lineas_by_order.setdefault(deduccion.order_id, []).append((deduccion.code, deduccion.monto, concepto))

    for row in rows:
        result[row.order_id] = OrderMetrics(
            order_id=row.order_id,
            neto=row.neto,
            neto_sin_iva=row.neto_sin_iva,
            iva_reconcilia=row.iva_reconcilia,
            costo_mercaderia=row.costo_mercaderia,
            total_gauss=row.total_gauss,
            markup_pct=row.markup_pct,
            gauss_status=GaussStatus(row.gauss_status),
            provisional_falta=row.provisional_falta,
            unresolved_reason=row.unresolved_reason,
            formula_version=row.formula_version,
            computed_at=row.computed_at,
            lineas=lineas_by_order.get(row.order_id, []),
        )
    return result


def metrics_state_for_orders(db: Session, order_ids: Sequence[int]) -> Dict[int, str]:
    """`metrics_state` per `order_id` (design D9, PR7.T4): one of `'ok'`,
    `'provisional'`, `'unresolved'`, `'recalculating'`, `'failed'`,
    `'pending'`. Precedence, in order:

    1. `'failed'` -- the dirty row is PARKED (`attempts >= POISON_THRESHOLD`).
       Wins over everything else: a parked order is never shown as
       `recalculating` forever, since nothing will retry it automatically.
    2. `'recalculating'` -- a dirty row exists (not parked). Wins over the
       stored status: the stored row may be stale mid-flight.
    3. the stored `gauss_status` (`'ok'` | `'provisional'` | `'unresolved'`)
       when a `ml_order_metrics` row exists and is not dirty.
    4. `'pending'` -- no `ml_order_metrics` row at all yet.

    Bulk: two queries total for the whole `order_ids` batch, never one
    query per order."""
    order_ids = list(order_ids)
    result: Dict[int, str] = {}
    if not order_ids:
        return result

    dirty_rows = (
        db.query(MlOrderMetricsDirty.order_id, MlOrderMetricsDirty.attempts)
        .filter(MlOrderMetricsDirty.order_id.in_(order_ids))
        .all()
    )
    attempts_by_order: Dict[int, int] = {row.order_id: row.attempts for row in dirty_rows}

    stored_rows = (
        db.query(MlOrderMetrics.order_id, MlOrderMetrics.gauss_status)
        .filter(MlOrderMetrics.order_id.in_(order_ids))
        .all()
    )
    status_by_order: Dict[int, str] = {row.order_id: row.gauss_status for row in stored_rows}

    for order_id in order_ids:
        attempts = attempts_by_order.get(order_id)
        if attempts is not None and attempts >= POISON_THRESHOLD:
            result[order_id] = "failed"
        elif attempts is not None:
            result[order_id] = "recalculating"
        elif order_id in status_by_order:
            result[order_id] = status_by_order[order_id]
        else:
            result[order_id] = "pending"
    return result

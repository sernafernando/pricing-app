"""The single writer of Gauss metrics (design D7). `recompute_order_metrics`
absorbs `persistir_total_gauss`'s write side: upserts `ml_order_metrics` +
`ml_venta_deducciones` + the legacy `ml_orders_ops.total_gauss*` sort-key
columns (design D1: kept until a later cleanup PR). NEVER commits -- the
caller controls the transaction, exactly like `persistir_total_gauss` did.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Sequence

from sqlalchemy.orm import Session

from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.services.ml_ventas_desglose.deducciones import DEDUCCIONES
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.types import GaussStatus, OrderMetrics


def recompute_order_metrics(db: Session, order_ids: Sequence[int]) -> Dict[int, OrderMetrics]:
    """Computes (via `compute.compute_order_metrics`, the single producer)
    and upserts `order_ids`' metrics. Returns the same `OrderMetrics` it
    stored, so a caller (e.g. `persistir_total_gauss`) never needs a second
    read to report what it just wrote."""
    order_ids = list(order_ids)
    if not order_ids:
        return {}

    metrics_by_order = compute_order_metrics(db, order_ids)

    orders = db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_(order_ids)).all()
    orders_by_id = {o.order_id: o for o in orders}

    existing_metrics = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id.in_(order_ids)).all()
    existing_metrics_by_id = {m.order_id: m for m in existing_metrics}

    existing_deducciones = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id.in_(order_ids)).all()
    existing_by_key = {(row.order_id, row.code): row for row in existing_deducciones}

    orden_by_code = {d.code: d.orden for d in DEDUCCIONES}

    now = datetime.now(timezone.utc)

    for order_id, metrics in metrics_by_order.items():
        order = orders_by_id.get(order_id)
        if order is not None:
            order.total_gauss = metrics.total_gauss
            order.total_gauss_at = now
            order.total_gauss_stale = False
            order.total_gauss_provisional = metrics.gauss_status == GaussStatus.PROVISIONAL

        metrics_row = existing_metrics_by_id.get(order_id)
        if metrics_row is None:
            metrics_row = MlOrderMetrics(order_id=order_id)
            db.add(metrics_row)
            existing_metrics_by_id[order_id] = metrics_row
        metrics_row.neto = metrics.neto
        metrics_row.neto_sin_iva = metrics.neto_sin_iva
        metrics_row.iva_reconcilia = metrics.iva_reconcilia
        metrics_row.costo_mercaderia = metrics.costo_mercaderia
        metrics_row.total_gauss = metrics.total_gauss
        metrics_row.markup_pct = metrics.markup_pct
        metrics_row.gauss_status = metrics.gauss_status.value
        metrics_row.provisional_falta = metrics.provisional_falta
        metrics_row.unresolved_reason = metrics.unresolved_reason
        metrics_row.formula_version = metrics.formula_version
        metrics_row.computed_at = metrics.computed_at

        for code, monto, _concepto in metrics.lineas:
            key = (order_id, code)
            deduccion_row = existing_by_key.get(key)
            if deduccion_row is None:
                deduccion_row = MlVentaDeduccion(order_id=order_id, code=code, orden=orden_by_code[code], monto=monto)
                db.add(deduccion_row)
                existing_by_key[key] = deduccion_row
            else:
                deduccion_row.orden = orden_by_code[code]
                deduccion_row.monto = monto

        # A deduction that stopped applying loses its row (persistir_total_
        # gauss's own rule, deducciones.py ~685-698) -- never left carrying a
        # freight/percent amount that is no longer owed.
        vigentes = {code for code, _monto, _concepto in metrics.lineas}
        for (row_order_id, code), deduccion_row in list(existing_by_key.items()):
            if row_order_id == order_id and code not in vigentes:
                db.delete(deduccion_row)
                del existing_by_key[(row_order_id, code)]

    return metrics_by_order

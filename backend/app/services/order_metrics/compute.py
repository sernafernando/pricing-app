"""The single producer of Gauss metrics (design D7). `compute_order_metrics`
WRAPS the existing formula functions -- `compute_neto_by_order_ids`,
`descomponer_neto`, `calcular_total_gauss` -- and returns identical values to
calling those directly. No second formula anywhere.

Pure reads, bulk by `order_ids`, no writes and no commit."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_ventas_desglose.breakdown_service import compute_neto_by_order_ids
from app.services.ml_ventas_desglose.deducciones import CostoMercaderiaDeduccion, calcular_total_gauss
from app.services.ml_ventas_desglose.iva import descomponer_neto
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.order_metrics.types import GaussStatus, OrderMetrics

logger = logging.getLogger(__name__)


def compute_order_metrics(db: Session, order_ids: Sequence[int]) -> Dict[int, OrderMetrics]:
    """One `OrderMetrics` per `order_id`, resolved with the SAME bulk calls
    (and therefore the SAME query count) `persistir_total_gauss` used to
    make directly -- never a second formula, never one query per order.

    An `order_id` with no `ml_orders_ops` row is silently SKIPPED, never
    raised and never present in the returned dict -- the exact tolerance
    the legacy `persistir_total_gauss` had (it iterated whatever came back,
    never indexed a required key). `ml_order_metrics.order_id` carries a
    hard FK to `ml_orders_ops`, so a metrics row for a nonexistent order
    would abort the flush; skipping it here is the only correct choice, not
    just a compatibility shim."""
    order_ids = list(order_ids)
    result: Dict[int, OrderMetrics] = {}
    if not order_ids:
        return result

    existing_order_ids = {
        row.order_id for row in db.query(MlOrdersOps.order_id).filter(MlOrdersOps.order_id.in_(order_ids)).all()
    }
    order_ids = [order_id for order_id in order_ids if order_id in existing_order_ids]
    if not order_ids:
        return result

    neto_by_order = compute_neto_by_order_ids(db, order_ids)
    descomposiciones = descomponer_neto(db, order_ids)
    neto_sin_iva_by_order = {oid: desc.neto_sin_iva for oid, desc in descomposiciones.items()}
    venta_sin_iva_by_order = {oid: desc.base_venta_sin_iva for oid, desc in descomposiciones.items()}

    resultados = calcular_total_gauss(
        db, order_ids, neto_sin_iva_by_order, venta_sin_iva_by_order=venta_sin_iva_by_order
    )

    computed_at = datetime.now(timezone.utc)

    for order_id in order_ids:
        resultado = resultados[order_id]
        descomposicion = descomposiciones.get(order_id)

        costo_mercaderia: Optional[Decimal] = next(
            (monto for code, monto, _concepto in resultado.lineas if code == CostoMercaderiaDeduccion.code),
            None,
        )

        if resultado.total_gauss is None:
            gauss_status = GaussStatus.UNRESOLVED
            # First blocking line names the reason -- never a generic
            # "unknown" when the chain itself already knows which link
            # broke (design D2 `unresolved_reason`).
            unresolved_reason: Optional[str] = next(
                (code for code, monto, _concepto in resultado.lineas if monto is None),
                None,
            )
        else:
            gauss_status = GaussStatus.PROVISIONAL if resultado.provisional else GaussStatus.OK
            unresolved_reason = None

        # `costo_mercaderia` (read off `resultado.lineas` by code, above) and
        # `resultado.markup` (computed by `calcular_total_gauss` from its
        # OWN local copy of the same cost) are two independent reads of the
        # same chain run -- they agree today, but `OrderMetrics.__post_init__`
        # would crash the whole write path if a future formula change ever
        # made them drift. Normalize here instead of letting the producer
        # raise (deducciones.py's own None-if-zero-or-unknown rule, ~562-571).
        markup_pct = resultado.markup
        if markup_pct is not None and (costo_mercaderia is None or costo_mercaderia == 0):
            logger.warning(
                "order_metrics: markup_pct=%s disagreed with costo_mercaderia=%s for order_id=%s -- normalized to None",
                markup_pct,
                costo_mercaderia,
                order_id,
            )
            markup_pct = None

        result[order_id] = OrderMetrics(
            order_id=order_id,
            neto=neto_by_order.get(order_id),
            neto_sin_iva=descomposicion.neto_sin_iva if descomposicion else None,
            iva_reconcilia=descomposicion.reconcilia if descomposicion else None,
            costo_mercaderia=costo_mercaderia,
            total_gauss=resultado.total_gauss,
            markup_pct=markup_pct,
            gauss_status=gauss_status,
            provisional_falta=resultado.provisional_falta,
            unresolved_reason=unresolved_reason,
            formula_version=CURRENT_FORMULA_VERSION,
            computed_at=computed_at,
            lineas=resultado.lineas,
        )

    return result

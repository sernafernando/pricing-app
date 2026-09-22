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


# `ml_order_metrics.markup_pct` is NUMERIC(9, 2): anything whose absolute
# value exceeds this cannot be stored, and on Postgres the INSERT would raise
# and abort the caller's whole transaction (the sweep batch, through
# `persistir_total_gauss`).
MARKUP_PCT_MAX = Decimal("9999999.99")


def normalize_markup_pct(
    markup_pct: Optional[Decimal],
    costo_mercaderia: Optional[Decimal],
    gauss_status: GaussStatus,
    *,
    order_id: int,
) -> Optional[Decimal]:
    """The markup to STORE, or None when it is unknown.

    The producer must never raise on the write path, so every value the
    stored row cannot hold, or that contradicts the order's own state,
    becomes NULL (unknown) with a warning -- never clamped, never
    fabricated:

    - no cost, or a zero cost: division by zero, same rule as
      `deducciones.py` (~562-571);
    - an unresolved order: its Total Gauss is NULL, so no markup can exist;
    - a value beyond `MARKUP_PCT_MAX`: e.g. a 0.01 frozen unit cost on a
      normal-priced order. A markup of millions of percent is a data
      problem in the cost, not a number worth showing.
    """
    if markup_pct is None:
        return None
    reason = None
    if costo_mercaderia is None or costo_mercaderia == 0:
        reason = "cost is missing or zero"
    elif gauss_status == GaussStatus.UNRESOLVED:
        reason = "order is unresolved"
    elif abs(markup_pct) > MARKUP_PCT_MAX:
        reason = "value exceeds the stored column"
    if reason is None:
        return markup_pct
    logger.warning(
        "order_metrics: markup_pct=%s normalized to None for order_id=%s (%s; costo_mercaderia=%s)",
        markup_pct,
        order_id,
        reason,
        costo_mercaderia,
    )
    return None


def compute_order_metrics(db: Session, order_ids: Sequence[int]) -> Dict[int, OrderMetrics]:
    """One `OrderMetrics` per `order_id`, resolved with the SAME formula
    functions `persistir_total_gauss` used to call directly
    (`descomponer_neto`, `calcular_total_gauss`) -- never a second formula.
    The query COUNT is NOT identical to the legacy path: this function
    issues two BULK queries the legacy caller did not need -- one existence
    check against `ml_orders_ops` (the `existing_order_ids` filter above,
    the legacy-tolerance skip this class's own docstring describes) and one
    `compute_neto_by_order_ids` call (this dataclass's own `neto` field,
    which `TotalGaussResultado` never carried). Both are bulk, ONE query
    each for the whole batch -- still O(1) per batch, never one per order,
    the same discipline every formula function here already follows.

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
        resultado = resultados.get(order_id)
        if resultado is None:
            # Legacy tolerance: `persistir_total_gauss` iterated the result
            # dict and never indexed a required key. An order the chain did
            # not return is skipped, never allowed to abort the batch.
            logger.warning("order_metrics: no chain result for order_id=%s -- skipped", order_id)
            continue
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
            if unresolved_reason is None:
                # No chain line is unknown, so the gap is upstream of the
                # chain: the starting value itself. Name it rather than
                # storing a reasonless unresolved row.
                if (
                    descomposicion is not None
                    and descomposicion.neto_sin_iva is None
                    and descomposicion.reconcilia is False
                ):
                    unresolved_reason = "iva_no_reconcilia"
                elif neto_by_order.get(order_id) is None:
                    unresolved_reason = "sin_pagos"
                else:
                    unresolved_reason = "neto_sin_iva_desconocido"
        else:
            gauss_status = GaussStatus.PROVISIONAL if resultado.provisional else GaussStatus.OK
            unresolved_reason = None

        markup_pct = normalize_markup_pct(resultado.markup, costo_mercaderia, gauss_status, order_id=order_id)

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

"""The shipping the BUYER pays (ventas-ml-varios-base-envio).

It is invoiced to the buyer, so it enters the "% de varios" base ("lo que
facturamos, después pagamos IIBB"): GROSS, even when ML later charges it back
(`shp_*`: +990 / -990). The charge keeps being subtracted where it is today;
this module only exposes the money that came in, split gross / net / IVA, for
the base and for an informational IVA line.

## Source: the money that CAME IN, per order

    envío del comprador = order.paid_amount - order.total_amount

`raw_costs.receiver.cost` is NOT used: ML annulled the 2216.30 of Flex pack
2000015400388457 ("Anulación del cargo por Envíos de Mercado Libre (a cargo
del comprador)") and `receiver.cost` still says 2216.30 while `paid_amount`
equals `total_amount`. The payment's `total_paid_amount - transaction_amount`
is not used either: it also carries the payer's `tax_withholding_payer`
(5107.54 instead of 4990 on order 2000018846969514).

Verified on every captured case (`tests/fixtures/ml_ventas_envio_comprador/`):
990, 4699.09, 3990, 4990, 5373.70 (three payments), and 0 for the annulled
pack.

PER ORDER, not per shipment: each order of a pack carries its own difference,
so nothing is split (the Flex bonificación, which IS per shipment, lives in
`bonificacion_flex.py`; the two are different concepts and never read each
other, so nothing is counted twice).

The visible IVA line "Envío cobrado al comprador" (`iva.py`) is built from
`payment.shipping_amount` of the relevant payments. It is a second reading of
the same money and agrees with this difference on every capture
(`test_the_base_and_the_visible_line_agree_on_every_capture`); no second line
is added for it.

## Fail-closed

A null or non-numeric amount, or a NEGATIVE difference, adds nothing and logs
a warning with the `order_id`. Never an exception (this runs inside the
metrics recompute). If the shipment's `receiver_cost` disagrees with the
difference, the difference wins and a debug line says so: an annulment makes
that legitimate.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class EnvioCompradorOrden:
    """What the buyer paid for shipping on ONE order. `bruto` is IVA included,
    `neto` the same without IVA; both POSITIVE (the sign belongs to whoever
    puts it in a base)."""

    bruto: Decimal
    neto: Decimal


def _a_decimal(value: Any) -> Optional[Decimal]:
    """`value` as a finite `Decimal`, or `None` if it is not a trustworthy
    number. `bool` is an `int` in Python: `True` would be one peso."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    number = Decimal(str(value))
    return number if number.is_finite() else None


def envio_comprador_bruto(paid_amount: Any, total_amount: Any, order_id: Optional[int] = None) -> Optional[Decimal]:
    """The shipping the buyer paid, with IVA, or `None` for "nothing to add".

    `None` covers both "the buyer paid no shipping" (silent) and "we could
    not read it" (logged): either way no money is invented. Never raises."""
    paid = _a_decimal(paid_amount)
    total = _a_decimal(total_amount)
    if paid is None or total is None:
        logger.warning(
            "envio_comprador: order_id=%s paid_amount/total_amount missing or not a number; contributing nothing",
            order_id,
        )
        return None
    difference = (paid - total).quantize(_CENT, rounding=ROUND_HALF_UP)
    if difference < 0:
        logger.warning(
            "envio_comprador: order_id=%s paid_amount is below total_amount (%s); contributing nothing",
            order_id,
            difference,
        )
        return None
    return difference if difference > 0 else None


def resolve_envio_comprador_by_order_ids(
    db: Session, order_ids: Sequence[int], divisor: Decimal
) -> Dict[int, EnvioCompradorOrden]:
    """Per-order shipping the buyer paid. An order WITHOUT a key has none:
    the buyer paid nothing, the amounts are unreadable, or the order does not
    exist. It is never a lying zero and never blocks anything.

    `divisor` is the IVA divisor ML's figures carry (`iva.IVA_ML_DIVISOR`),
    passed in so this module does not import `iva` (which imports it).

    Bulk: ONE query for the whole batch (plus one more only when debug
    logging is on), never one per order."""
    order_ids = list(order_ids)
    result: Dict[int, EnvioCompradorOrden] = {}
    if not order_ids:
        return result

    rows = (
        db.query(MlOrdersOps.order_id, MlOrdersOps.paid_amount, MlOrdersOps.total_amount, MlOrdersOps.shipping_id)
        .filter(MlOrdersOps.order_id.in_(order_ids))
        .all()
    )
    shipping_by_order: Dict[int, Optional[int]] = {}
    bruto_by_order: Dict[int, Optional[Decimal]] = {}
    for order_id, paid_amount, total_amount, shipping_id in rows:
        shipping_by_order[order_id] = shipping_id
        bruto = envio_comprador_bruto(paid_amount, total_amount, order_id)
        bruto_by_order[order_id] = bruto
        if bruto is not None:
            neto = (bruto / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)
            result[order_id] = EnvioCompradorOrden(bruto=bruto, neto=neto)

    if logger.isEnabledFor(logging.DEBUG):
        _log_receiver_cost_disagreements(db, shipping_by_order, bruto_by_order)
    return result


def _log_receiver_cost_disagreements(
    db: Session, shipping_by_order: Dict[int, Optional[int]], bruto_by_order: Dict[int, Optional[Decimal]]
) -> None:
    shipping_ids = sorted({s for s in shipping_by_order.values() if s is not None})
    if not shipping_ids:
        return
    receiver_cost_by_shipment = {
        shipment_id: receiver_cost
        for shipment_id, receiver_cost in db.query(MlShipmentOps.shipment_id, MlShipmentOps.receiver_cost)
        .filter(MlShipmentOps.shipment_id.in_(shipping_ids))
        .all()
    }
    for order_id, shipping_id in shipping_by_order.items():
        receiver_cost = receiver_cost_by_shipment.get(shipping_id)
        if receiver_cost is None:
            continue
        used = bruto_by_order.get(order_id) or Decimal("0")
        if Decimal(str(receiver_cost)) != used:
            logger.debug(
                "envio_comprador: order_id=%s uses paid_amount - total_amount=%s; shipment receiver_cost=%s differs "
                "(an annulment makes that legitimate)",
                order_id,
                used,
                receiver_cost,
            )

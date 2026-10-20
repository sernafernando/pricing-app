"""The shipping the BUYER pays (ventas-ml-varios-base-envio).

It is invoiced to the buyer, so it enters the "% de varios" base ("lo que
facturamos, después pagamos IIBB"): GROSS, even when ML later charges it back
(`shp_*`: +990 / -990). The charge keeps being subtracted where it is today;
this module only reads the money that came in, so the visible IVA line and the
varios base are built from the SAME amounts.

## First source: `payment.shipping_amount`

The explicit field ML labels as shipping, one value per payment. It is what
the visible line "Envío cobrado al comprador" (`iva.py`) has always read, and
the base now reads it through the same helper (`envio_comprador_de_pago`) and
the same aggregation: every RELEVANT payment of the order with a shipping
amount contributes once (a rejected payment never does), so an order with
three payments counts its shipping once, not three times.

## Flex fallback: `raw_costs.receiver.cost_details` (flex-envio-comprador)

On a Flex (`self_service`) shipment the buyer may pay the shipping to us
without the payment carrying it: order 2000018999267608 has
`shipping_amount` 0, and the ML panel still shows "Cargo por Envíos de
Mercado Libre (a cargo del comprador)" +5990, which is exactly
`receiver.cost_details = [{amount: 5990, sender_id: <the seller>}]`. Pack
2000015400388457 is the same case: its panel shows that line at $2.216,30, so
the 2216.30 was NOT annulled (an earlier version of this docstring said it
was, and rejected the shipment's costs for that reason).

Measured in production (2026-10-20): on 2,176 of 2,176 self_service
shipments whose payment carries the shipping and whose `cost_details` toward
the seller is present, the two amounts are equal. So the fallback is the same
money, read from where ML puts it when the payment does not:

1. if ANY relevant payment of ANY order of the shipment carries a shipping
   amount, the payment is the source and the fallback adds nothing;
2. otherwise, Σ `receiver.cost_details[].amount` whose `sender_id` is the
   order's own `seller_id`, split to the cent across the orders sharing the
   `shipping_id` (`repartir_en_centavos`, like the Flex bonificación).

ONLY `self_service`: on cross_docking / fulfillment ML takes that shipping
back with a `shp_*` charge (`buyer_shipping_capture_20261007.json`).

The fallback is NOT inside `net_received_amount`: it is a component outside
the payment (`fuera_del_pago`) like the Flex bonificación, and it enters
`neto` and the "% de varios" base the same way.

Deliberately NOT used:

- `order.paid_amount - order.total_amount`: an inference that also catches
  anything else the buyer paid on top of the goods, such as a financing
  surcharge. It matches `shipping_amount` on every captured case, but the
  field is the one ML names.
- `raw_costs.receiver.cost`: the total the receiver side costs, not who it
  is paid to; `cost_details` names the `sender_id` it goes to.
- the payment's `total_paid_amount - transaction_amount`: it also carries the
  payer's `tax_withholding_payer` (5107.54 instead of 4990 on order
  2000018846969514).

## Fail-closed

A non-numeric (a string, a bool, NaN/inf) or NEGATIVE amount adds nothing and
logs a warning with the `payment_id`. A null amount adds nothing and is
logged at debug (it is the normal state of a payment without shipping). Never
an exception: this runs inside the metrics recompute.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_orders_ingestion.mode_resolution import MODO_SELF_SERVICE
from app.services.ml_ventas_desglose.bonificacion_flex import repartir_en_centavos
from app.services.ml_ventas_desglose.breakdown_service import RELEVANT_PAYMENT_STATUSES, resolve_modes

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class EnvioCompradorOrden:
    """What the buyer paid for shipping on ONE order, gross and without IVA,
    both POSITIVE (the sign belongs to whoever puts it in a base)."""

    bruto: Decimal
    neto: Decimal


def envio_comprador_de_pago(shipping_amount: Any, payment_id: Optional[int] = None) -> Optional[Decimal]:
    """The shipping one payment carried, with IVA, or `None` for "nothing to
    add" (zero, null, or unreadable -- the unreadable ones are logged).
    Never raises."""
    if shipping_amount is None:
        logger.debug("envio_comprador: payment_id=%s has no shipping_amount", payment_id)
        return None
    # `bool` is an `int` in Python: `True` would be one peso.
    if isinstance(shipping_amount, bool) or not isinstance(shipping_amount, (int, float, Decimal)):
        logger.warning(
            "envio_comprador: payment_id=%s shipping_amount is not a number; contributing nothing", payment_id
        )
        return None
    if isinstance(shipping_amount, float) and not math.isfinite(shipping_amount):
        logger.warning("envio_comprador: payment_id=%s shipping_amount is not finite; contributing nothing", payment_id)
        return None
    value = Decimal(str(shipping_amount))
    if not value.is_finite():
        logger.warning("envio_comprador: payment_id=%s shipping_amount is not finite; contributing nothing", payment_id)
        return None
    if value < 0:
        logger.warning("envio_comprador: payment_id=%s shipping_amount is negative; contributing nothing", payment_id)
        return None
    return value if value > 0 else None


def _warn_costs(shipment_id: Optional[int], reason: str) -> None:
    logger.warning(
        "envio_comprador: shipment_id=%s raw_costs receiver.cost_details ignored (%s); contributing nothing",
        shipment_id,
        reason,
    )


def envio_comprador_flex_desde_raw_costs(
    raw_costs: Any, seller_id: Optional[int], shipment_id: Optional[int] = None
) -> Optional[Decimal]:
    """Σ `receiver.cost_details[].amount` paid toward `seller_id`, with IVA, or
    `None` for "nothing to add".

    Entries toward another `sender_id` are skipped. ONE unreadable entry toward
    the seller (or a payload of the wrong shape) voids the whole amount and
    logs a warning: never an invented amount, never an exception."""
    if raw_costs is None or seller_id is None:
        return None
    if not isinstance(raw_costs, dict):
        _warn_costs(shipment_id, "raw_costs is not an object")
        return None
    receiver = raw_costs.get("receiver")
    if receiver is None:
        return None
    if not isinstance(receiver, dict):
        _warn_costs(shipment_id, "receiver is not an object")
        return None
    details = receiver.get("cost_details")
    if details is None:
        return None
    if not isinstance(details, list):
        _warn_costs(shipment_id, "cost_details is not a list")
        return None

    total = Decimal("0")
    for entry in details:
        if not isinstance(entry, dict):
            _warn_costs(shipment_id, "a cost_details entry is not an object")
            return None
        if entry.get("sender_id") != seller_id:
            continue
        amount = entry.get("amount")
        # `bool` is an `int` in Python: `True` would be read as one peso.
        if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
            _warn_costs(shipment_id, "amount is missing or not a number")
            return None
        if isinstance(amount, float) and not math.isfinite(amount):
            _warn_costs(shipment_id, "amount is not finite")
            return None
        value = Decimal(str(amount))
        if not value.is_finite() or value < 0:
            _warn_costs(shipment_id, "amount is negative or not finite")
            return None
        total += value

    total = total.quantize(_CENT, rounding=ROUND_HALF_UP)
    return total if total > 0 else None


def resolve_envio_comprador_flex_by_order_ids(
    db: Session, order_ids: Sequence[int], divisor: Decimal
) -> Dict[int, EnvioCompradorOrden]:
    """Per-order share of the Flex buyer-paid shipping that NO payment carries
    (see "Flex fallback" above). An order without a key has none: not Flex, a
    payment of its shipment already carries the shipping, no cost payload yet,
    or nothing readable toward the seller.

    `divisor` is `iva.IVA_ML_DIVISOR`, passed in so this module does not import
    `iva` (which imports it). Bulk: a handful of queries for the whole batch."""
    order_ids = list(order_ids)
    result: Dict[int, EnvioCompradorOrden] = {}
    if not order_ids:
        return result

    orders = db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_(order_ids)).all()
    modes_by_order, shipments_by_id = resolve_modes(db, orders)

    bruto_by_shipment: Dict[int, Decimal] = {}
    for order in orders:
        shipping_id = order.shipping_id
        if shipping_id is None or modes_by_order.get(order.order_id) != MODO_SELF_SERVICE:
            continue
        if shipping_id in bruto_by_shipment:
            continue
        shipment = shipments_by_id.get(shipping_id)
        bruto = envio_comprador_flex_desde_raw_costs(
            shipment.raw_costs if shipment else None, order.seller_id, shipping_id
        )
        if bruto is not None:
            bruto_by_shipment[shipping_id] = bruto
    if not bruto_by_shipment:
        return result

    # The members come from the DATABASE, not from `order_ids`: the split and
    # the "a payment carries it" check are about the whole shipment.
    members: Dict[int, List[int]] = {}
    for member_id, shipping_id in (
        db.query(MlOrdersOps.order_id, MlOrdersOps.shipping_id)
        .filter(MlOrdersOps.shipping_id.in_(sorted(bruto_by_shipment)))
        .order_by(MlOrdersOps.order_id)
        .all()
    ):
        members.setdefault(shipping_id, []).append(member_id)

    all_members = [member_id for ids in members.values() for member_id in ids]
    orders_with_paid_shipping = {
        order_id
        for order_id, status, shipping_amount, payment_id in db.query(
            MlPaymentOps.order_id, MlPaymentOps.status, MlPaymentOps.shipping_amount, MlPaymentOps.payment_id
        )
        .filter(MlPaymentOps.order_id.in_(all_members))
        .all()
        if status in RELEVANT_PAYMENT_STATUSES and envio_comprador_de_pago(shipping_amount, payment_id) is not None
    }

    wanted = set(order_ids)
    for shipping_id, bruto in bruto_by_shipment.items():
        ids = members.get(shipping_id, [])
        if not ids or any(member_id in orders_with_paid_shipping for member_id in ids):
            continue
        neto = (bruto / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)
        bruto_shares = repartir_en_centavos(bruto, len(ids))
        neto_shares = repartir_en_centavos(neto, len(ids))
        for member_id, bruto_share, neto_share in zip(ids, bruto_shares, neto_shares):
            if member_id in wanted:
                result[member_id] = EnvioCompradorOrden(bruto=bruto_share, neto=neto_share)
    return result

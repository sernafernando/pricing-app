"""The Flex "Bonificación por envío" (ventas-ml-bonificacion-envio-flex).

On a Flex sale (`logistic_type = self_service`) ML pays the SELLER a
bonificación for the shipping the seller delivers. That money is income, and
it is in none of the places the net is built from: not in
`net_received_amount`, not in billing, not in `/orders/{id}/discounts` (404).
It sits only in the shipment's costs payload, which
`ml_shipments_ops.raw_costs` stores verbatim.

## What counts (ventas-ml-varios-base-envio corrected the first rule)

    bonificación = Σ senders[].discounts[].promoted_amount
                 + Σ receiver.discounts[type == "loyal"].promoted_amount

Two real samples, both checked against ML's own panel:

- Sale 2000018808335864: `receiver.discounts = [{type: loyal, rate: 1,
  promoted_amount: 8990}]`, `senders[0].discounts = []`; the panel shows
  $8.990.
- Pack 2000015400388457 (order 2000018846584294):
  `senders[0].discounts = [{type: mandatory, promoted_amount: 599}]` and
  `receiver.discounts = [{type: ratio, rate: 0.63, promoted_amount:
  3773.7}]`; the panel shows $599. The `ratio` 3773.7 is ML's subsidy to the
  BUYER, not the seller's income. The first version of this module summed
  every `receiver.discounts` and read 3773.7 there.

The rule rests on those TWO samples. It is not a general statement about
ML's API: a `receiver.discounts` type that is neither `loyal` nor a known
non-income type (`ratio`) is NEVER assumed to be income -- it adds nothing
and logs a warning with the shipment id, so the next unseen type shows up in
the log instead of in the money. Sender discounts are summed whatever their
`type` (only `mandatory` has been captured), exactly like the candidate rule.

ONLY `self_service`: on drop-off / fulfillment the discounts are subsidies
and not income for the seller. Same per-order mode `compute_breakdown` and
the Flex freight use (`resolve_modes`).

## Fail-closed

A missing, non-numeric (a string, a bool, NaN/inf) or negative
`promoted_amount` never adds money. ONE unreadable entry (or a `senders` /
`receiver` / `discounts` of the wrong shape) voids the whole shipment's
amount: a valid 599 next to an entry we cannot read would present as ML's
payment a figure we cannot show adds up to what ML paid. "When in doubt,
nothing, and a log" -- never an invented amount, never an exception on the
write path (this runs inside the metrics recompute).

An absent / unsynced cost payload is the NORMAL state of a young sale and
is silent: the shipment trigger on `raw_costs` recomputes the sale the
moment it lands.

## One shipment, one bonificación

A pack can hold several orders under a single `shipping_id`; the payment is
for the SHIPMENT. Every order would otherwise read the whole amount and the
group total (which sums its members) would count it once per order. Same
criterion as `EnvioFlexDeduccion`: the divisor is the number of orders
sharing the `shipping_id` IN THE DATABASE, never in the batch (a number
that changed when you scrolled would be worse than a wrong one).

Unlike the freight, the split is EXACT to the cent: gross and net are each
distributed so their shares add up to the shipment's amount, the remainder
cents going to the lowest `order_id`s. `iva = bruto - neto` per share, so
`base + iva == bruto` holds like every component of `iva.py`.

This module is the ONE place the bonificación is computed: the neto
(`breakdown_service`), the IVA component (`iva.py`) and the "% de varios" base
all read `resolve_bonificacion_flex_by_order_ids`.

Where it lives (ventas-ml-bonificacion-en-neto): ML pays it for the operation,
so it is part of ML's NETO -- gross in `neto`, net of IVA in `neto_sin_iva` --
and NOT a deduction of the Total Gauss chain. The Total Gauss reaches the same
figure through `neto_sin_iva`.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_orders_ingestion.mode_resolution import MODO_SELF_SERVICE
from app.services.ml_ventas_desglose.breakdown_service import resolve_modes

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class BonificacionOrden:
    """One order's share of its shipment's bonificación. `bruto` is what ML
    pays (IVA included); `neto` the same without IVA. Both are POSITIVE:
    the sign belongs to whoever puts it in a chain."""

    bruto: Decimal
    neto: Decimal


def _warn(shipment_id: Optional[int], reason: str) -> None:
    logger.warning(
        "bonificacion_flex: shipment_id=%s raw_costs discounts ignored (%s); contributing nothing",
        shipment_id,
        reason,
    )


# `receiver.discounts` types that are KNOWN not to be the seller's income:
# `ratio` is ML's subsidy to the buyer (captured on the pack whose panel
# bonificación is the sender's 599, not this 3773.7).
_RECEIVER_TIPOS_QUE_NO_SON_INGRESO = frozenset({"ratio"})
_RECEIVER_TIPO_INGRESO = "loyal"


def _importe_promovido(entry: Dict[str, Any], shipment_id: Optional[int]) -> Optional[Decimal]:
    """`promoted_amount` of one discount entry, or `None` if it cannot be
    trusted (logged)."""
    amount = entry.get("promoted_amount")
    # `bool` is an `int` in Python: `True` would be read as one peso.
    if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
        _warn(shipment_id, "promoted_amount is missing or not a number")
        return None
    if isinstance(amount, float) and not math.isfinite(amount):
        _warn(shipment_id, "promoted_amount is not finite")
        return None
    value = Decimal(str(amount))
    if not value.is_finite() or value < 0:
        _warn(shipment_id, "promoted_amount is negative or not finite")
        return None
    return value


def _lista_de_descuentos(container: Dict[str, Any], what: str, shipment_id: Optional[int]) -> Optional[List[Any]]:
    """`container["discounts"]` as a list: `[]` when absent, `None` (logged)
    when it is not a list."""
    discounts = container.get("discounts")
    if discounts is None:
        return []
    if not isinstance(discounts, list):
        _warn(shipment_id, f"{what} discounts is not a list")
        return None
    return discounts


def bonificacion_bruta_desde_raw_costs(raw_costs: Any, shipment_id: Optional[int] = None) -> Optional[Decimal]:
    """The shipment's bonificación with IVA, or `None` for "nothing to add".

    `None` covers both "there is no bonificación" (silent) and "we could not
    read it" (logged): either way no money is invented. Never raises."""
    if raw_costs is None:
        return None
    if not isinstance(raw_costs, dict):
        _warn(shipment_id, "raw_costs is not an object")
        return None

    total = Decimal("0")

    senders = raw_costs.get("senders")
    if senders is not None:
        if not isinstance(senders, list):
            _warn(shipment_id, "senders is not a list")
            return None
        for sender in senders:
            if not isinstance(sender, dict):
                _warn(shipment_id, "a sender is not an object")
                return None
            sender_discounts = _lista_de_descuentos(sender, "sender", shipment_id)
            if sender_discounts is None:
                return None
            for entry in sender_discounts:
                if not isinstance(entry, dict):
                    _warn(shipment_id, "a sender discount entry is not an object")
                    return None
                value = _importe_promovido(entry, shipment_id)
                if value is None:
                    return None
                total += value

    receiver = raw_costs.get("receiver")
    if receiver is not None:
        if not isinstance(receiver, dict):
            _warn(shipment_id, "receiver is not an object")
            return None
        receiver_discounts = _lista_de_descuentos(receiver, "receiver", shipment_id)
        if receiver_discounts is None:
            return None
        for entry in receiver_discounts:
            if not isinstance(entry, dict):
                _warn(shipment_id, "a discount entry is not an object")
                return None
            tipo = entry.get("type")
            if tipo in _RECEIVER_TIPOS_QUE_NO_SON_INGRESO:
                continue
            if tipo != _RECEIVER_TIPO_INGRESO:
                # Never assume an unseen type is income.
                _warn(shipment_id, f"receiver discount type {tipo!r} is unknown, not counted as income")
                continue
            value = _importe_promovido(entry, shipment_id)
            if value is None:
                return None
            total += value

    total = total.quantize(_CENT, rounding=ROUND_HALF_UP)
    return total if total > 0 else None


def repartir_en_centavos(total: Decimal, n: int) -> List[Decimal]:
    """`total` split into `n` shares that add up to it EXACTLY: the first
    `total_cents % n` shares carry one extra cent."""
    cents = int((total * 100).to_integral_value(rounding=ROUND_HALF_UP))
    base, resto = divmod(cents, n)
    return [Decimal(base + (1 if i < resto else 0)) / Decimal(100) for i in range(n)]


def resolve_bonificacion_flex_by_order_ids(
    db: Session, order_ids: Sequence[int], divisor: Decimal
) -> Dict[int, BonificacionOrden]:
    """Per-order share of the Flex bonificación. An order WITHOUT a key has
    none: not Flex, no payload yet, nothing readable, or nothing paid. It is
    never a lying zero and never blocks anything.

    `divisor` is the IVA divisor ML's figures carry (`iva.IVA_ML_DIVISOR`),
    passed in so this module does not import `iva` (which imports it).

    Bulk: a handful of queries for the whole batch, never one per order."""
    order_ids = list(order_ids)
    result: Dict[int, BonificacionOrden] = {}
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
        bruto = bonificacion_bruta_desde_raw_costs(shipment.raw_costs if shipment else None, shipping_id)
        if bruto is not None:
            bruto_by_shipment[shipping_id] = bruto
    if not bruto_by_shipment:
        return result

    # The members come from the DATABASE, not from `order_ids`.
    members: Dict[int, List[int]] = {}
    for member_id, shipping_id in (
        db.query(MlOrdersOps.order_id, MlOrdersOps.shipping_id)
        .filter(MlOrdersOps.shipping_id.in_(sorted(bruto_by_shipment)))
        .order_by(MlOrdersOps.order_id)
        .all()
    ):
        members.setdefault(shipping_id, []).append(member_id)

    wanted = set(order_ids)
    for shipping_id, bruto in bruto_by_shipment.items():
        neto = (bruto / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)
        ids = members.get(shipping_id, [])
        if not ids:
            continue
        bruto_shares = repartir_en_centavos(bruto, len(ids))
        neto_shares = repartir_en_centavos(neto, len(ids))
        for member_id, bruto_share, neto_share in zip(ids, bruto_shares, neto_shares):
            if member_id in wanted:
                result[member_id] = BonificacionOrden(bruto=bruto_share, neto=neto_share)
    return result

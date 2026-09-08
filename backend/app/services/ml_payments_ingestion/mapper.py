"""Pure mapping from raw Mercado Pago payment payloads (`get_payment`) to
`PaymentDTO`/`ChargeDTO` DTOs (ml-ventas-desglose-costos, corte 5).

No I/O, no DB — fully unit-testable against fixtures, mirroring the
`ml_billing_ingestion/mapper.py` fail-closed contract: `map_payment`
NEVER raises. It returns either a populated `PaymentDTO` or a
`MappingError`, so a caller can never observe a partially-populated DTO.

Unknown-fields contract (obs #1965): the proxy's payment payload is NOT
a closed set of 13 fields -- it can gain or drop fields across deploys
without coordination. This mapper therefore treats every field as
OPTIONAL except `payment_id`, `order_id`, and `status` (the three needed
to write a row at all); anything else missing simply maps to `None`, and
anything extra is silently ignored.

Charge shape (measured live, obs #1960): a charge line is FLAT --
`{name, type, amount, refunded}` -- there is no `amounts.original` /
`amounts.refunded` nesting anywhere in the real payload. Every charge is
stored VERBATIM here; the seller-vs-buyer/coupon exclusion rule is
applied entirely at READ time (see `app/models/ml_payments.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from dateutil.parser import isoparse

logger = logging.getLogger(__name__)


class MappingError:
    """Non-exception failure value returned by `map_payment`. See
    `ml_billing_ingestion/mapper.py::MappingError` for the same
    fail-closed return-value-union rationale."""

    __slots__ = ("reason", "raw_payload")

    def __init__(self, reason: str, raw_payload: Optional[Dict[str, Any]] = None) -> None:
        self.reason = reason
        self.raw_payload = raw_payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"MappingError(reason={self.reason!r})"


@dataclass(frozen=True)
class ChargeDTO:
    name: str
    type: Optional[str]
    amount: Optional[Decimal]
    refunded: Optional[Decimal]


@dataclass(frozen=True)
class PaymentDTO:
    payment_id: int
    order_id: int
    status: str
    currency_id: Optional[str]
    date_approved: Optional[datetime]
    transaction_amount: Optional[Decimal]
    shipping_amount: Optional[Decimal]
    coupon_amount: Optional[Decimal]
    total_paid_amount: Optional[Decimal]
    net_received_amount: Optional[Decimal]
    transaction_amount_refunded: Optional[Decimal]
    taxes_amount: Optional[Decimal]
    charges: List[ChargeDTO] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)


def _decimal(raw: Any) -> Optional[Decimal]:
    """`Decimal(str(...))`, NEVER `float(...)` -- same money-path rule as
    every other mapper in this codebase. Returns `None` for a missing
    value; lets `decimal.InvalidOperation`/`TypeError`/`ValueError`
    propagate to the caller's try/except, which turns it into a
    `MappingError`."""
    if raw is None:
        return None
    return Decimal(str(raw))


def _parse_tz_aware(value: Any) -> Optional[datetime]:
    """Same contract as `ml_orders_ingestion/mapper.py::_parse_tz_aware`:
    None/empty -> None, a naive result is defensively assumed UTC, an
    unparseable non-empty string raises."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise TypeError(f"date_approved is not a string: {value!r}")
    parsed = isoparse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _map_charge(raw: Any) -> ChargeDTO:
    if not isinstance(raw, dict):
        raise TypeError(f"charge is not an object: {raw!r}")
    name = raw.get("name")
    charge_type = raw.get("type")
    # `name` is required: without it the seller/buyer predicate cannot
    # classify the charge, and a charge we cannot classify would silently
    # land on the wrong side of the money.
    #
    # `type` is NOT required. ML sends it null on older charges, and
    # rejecting those cost the WHOLE payment: one untyped `meli_fee` and
    # the sale had no net at all. The predicate already treats a missing
    # type as "not one of the buyer's types", which is the safe reading.
    if not name:
        raise ValueError(f"charge missing name: {raw!r}")
    return ChargeDTO(
        name=str(name),
        # `is not None`, so an empty string is NOT quietly folded into a
        # missing type: null is what ML actually sends, and "" would be
        # dirty data that should look like it rather than blend in.
        type=str(charge_type) if charge_type is not None else None,
        amount=_decimal(raw.get("amount")),
        refunded=_decimal(raw.get("refunded")),
    )


def map_payment(raw: Any) -> Union[PaymentDTO, MappingError]:
    """Maps one raw `get_payment` payload into a `PaymentDTO`.

    Args:
        raw: The dict returned by `ml_webhook_client.get_payment`.

    Returns:
        A `PaymentDTO`, or a `MappingError` if the payload is malformed
        or missing a required field. Never raises.
    """
    if not isinstance(raw, dict):
        return MappingError(f"payment payload is not a dict: {type(raw).__name__}", None)

    try:
        raw_payment_id = raw.get("payment_id")
        raw_order_id = raw.get("order_id")
        status = raw.get("status")
        if raw_payment_id is None:
            return MappingError("missing payment_id", raw)
        if raw_order_id is None:
            return MappingError("missing order_id", raw)
        if not status:
            return MappingError("missing status", raw)

        payment_id = int(raw_payment_id)
        order_id = int(raw_order_id)
        status = str(status)

        raw_charges = raw.get("charges_details")
        if raw_charges is None:
            raw_charges = []
        if not isinstance(raw_charges, list):
            return MappingError(f"charges_details is not a list: {raw_charges!r}", raw)
        charges = [_map_charge(entry) for entry in raw_charges]

        return PaymentDTO(
            payment_id=payment_id,
            order_id=order_id,
            status=status,
            currency_id=raw.get("currency_id"),
            date_approved=_parse_tz_aware(raw.get("date_approved")),
            transaction_amount=_decimal(raw.get("transaction_amount")),
            shipping_amount=_decimal(raw.get("shipping_amount")),
            coupon_amount=_decimal(raw.get("coupon_amount")),
            total_paid_amount=_decimal(raw.get("total_paid_amount")),
            net_received_amount=_decimal(raw.get("net_received_amount")),
            transaction_amount_refunded=_decimal(raw.get("transaction_amount_refunded")),
            taxes_amount=_decimal(raw.get("taxes_amount")),
            charges=charges,
            raw_payload=raw,
        )
    # `ArithmeticError` covers `decimal.InvalidOperation` -- raised by
    # `Decimal(str(...))` on something like "N/A" -- which does NOT
    # inherit from `ValueError`. Omitting it would let a single malformed
    # amount escape this mapper and crash whatever sweep called it.
    except (TypeError, ValueError, ArithmeticError, AttributeError) as e:
        logger.warning(f"Error mapeando pago: {e}")
        return MappingError(str(e), raw)

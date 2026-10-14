"""Loads the REAL captures of payments carrying a `coupon_fee` charge
(`tests/fixtures/ml_charges/coupon_fee_capture_20261014.json`, captured
2026-10-14 from production: the payment row, every `ml_payment_charges` row
and the order items, untouched).

`coupon_fee` (`type='coupon'`) is the SELLER-funded part of a buyer's coupon.
ML deducts it from `net_received_amount`, so the IVA decomposition has to
account for it or the payment never reconciles. Never hand-write these
amounts: a fixture written by hand is an assumption about somebody else's API.

The item's frozen IVA rate is the one value the capture does not carry (it
lives in our catalogue, not in ML's payload); 21% is used for every item.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "ml_charges" / "coupon_fee_capture_20261014.json"

# payment_id of each captured case (the key of the fixture)
CANCELLED_COUPON_CODE_AND_FEE = 182717438169  # cancelled; coupon_code == coupon_fee == 8404.5
APPROVED_COUPON_FEE_ONLY = 183096662957  # approved; coupon_fee 2560 is the whole gap
APPROVED_COUPON_CODE_FEE_REBATE = 183081084229  # approved; coupon_code + coupon_fee + coupon_rebate + Flex charge

ITEM_IVA_PCT = Decimal("21")

_PAYMENT_MONEY = (
    "transaction_amount",
    "shipping_amount",
    "coupon_amount",
    "total_paid_amount",
    "net_received_amount",
    "transaction_amount_refunded",
    "taxes_amount",
)


def _money(value: Any) -> Decimal:
    # Through `str`: the capture is JSON floats, and `Decimal(float)` would
    # carry the binary representation error into an exact reconciliation.
    return Decimal(str(value))


def capture(payment_id: int) -> Dict[str, Any]:
    return copy.deepcopy(json.loads(FIXTURE.read_text())[str(payment_id)])


def coupon_fee_amount(payment_id: int) -> Decimal:
    (charge,) = [c for c in capture(payment_id)["charges"] if c["name"] == "coupon_fee"]
    return _money(charge["amount"])


def seed_capture(db, payment_id: int) -> int:
    """Seeds the captured order, payment, charges and items. Returns the
    order_id."""
    data = capture(payment_id)
    order_id = data["order_id"]
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 10, 14, tzinfo=timezone.utc),
            seller_id=999,
        )
    )
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status=data["status"],
            **{key: _money(data[key]) for key in _PAYMENT_MONEY},
        )
    )
    for charge in data["charges"]:
        db.add(
            MlPaymentCharge(
                payment_id=payment_id,
                name=charge["name"],
                type=charge["type"],
                amount=_money(charge["amount"]),
                refunded=_money(charge["refunded"]),
            )
        )
    for item in data["items"]:
        precio = _money(item["unit_price"])
        db.add(
            MlOrderItemOps(
                order_id=order_id,
                item_id=item["item_id"],
                variation_id=None,
                seller_sku="SKU-1",
                quantity=item["quantity"],
                unit_price=precio,
            )
        )
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id=item["item_id"],
                variation_id=None,
                costo_origen=Decimal("50.00"),
                moneda="ARS",
                tipo_cambio=None,
                tipo_cambio_fecha=None,
                costo_unitario_ars=Decimal("50.00"),
                iva_pct=ITEM_IVA_PCT,
                precio_unitario=precio,
                fuente="sku",
                producto_item_id=1,
            )
        )
    db.commit()
    return order_id

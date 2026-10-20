"""Loads the REAL `raw_costs` of two Flex shipments
(`tests/fixtures/ml_ventas_envio_comprador/flex_receiver_costs_capture_20261020.json`,
read verbatim from production on 2026-10-20).

Only the cost payload comes from ML. The order, item and payment rows are our
own tables, seeded with the figures of order 2000018999267608 as the ML panel
and our payment row show them: 2 x 7000, `net_received_amount` 9044 and
`shipping_amount` 0. The panel shows "Cargo por Envíos de Mercado Libre (a
cargo del comprador)" +5990, which is exactly `receiver.cost_details` toward
the seller.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "ml_ventas_envio_comprador"
    / "flex_receiver_costs_capture_20261020.json"
)

SHIPMENT_5990 = 48267372588
ORDER_5990 = 2000018999267608
PAYMENT_5990 = 900000000001


def raw_costs(shipment_id: int) -> Dict[str, Any]:
    shipments = json.loads(FIXTURE.read_text())["shipments"]
    return copy.deepcopy(next(s["raw_costs"] for s in shipments if s["shipment_id"] == shipment_id))


def seller_id(shipment_id: int) -> int:
    """The seller of the capture: the sender of the shipment."""
    return raw_costs(shipment_id)["senders"][0]["user_id"]


def seed_order_5990(
    db,
    *,
    logistic_type: str = "self_service",
    shipping_amount: float = 0.0,
    net_received_amount: float = 9044.0,
    costs: Any = ...,
) -> None:
    """Order 2000018999267608 with its shipment's REAL `raw_costs` (or `costs`,
    a payload derived from it)."""
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    db.add(
        MlOrdersOps(
            order_id=ORDER_5990,
            seller_id=seller_id(SHIPMENT_5990),
            status="paid",
            total_amount=14000.0,
            paid_amount=14000.0 + shipping_amount,
            currency_id="ARS",
            shipping_id=SHIPMENT_5990,
            date_created=now,
            ml_last_updated=now,
        )
    )
    db.add(MlOrderItemOps(order_id=ORDER_5990, item_id="MLA5990", quantity=2, unit_price=7000.0))
    db.add(
        MlOrderItemCosto(
            order_id=ORDER_5990,
            item_id="MLA5990",
            costo_origen=Decimal("1000.00"),
            moneda="ARS",
            costo_unitario_ars=Decimal("1000.00"),
            iva_pct=Decimal("21.00"),
            precio_unitario=Decimal("7000.00"),
            fuente="sku",
            producto_item_id=1,
        )
    )
    db.add(
        MlPaymentOps(
            payment_id=PAYMENT_5990,
            order_id=ORDER_5990,
            status="approved",
            transaction_amount=14000.0,
            shipping_amount=shipping_amount,
            net_received_amount=net_received_amount,
            transaction_amount_refunded=0.0,
            currency_id="ARS",
        )
    )
    db.add(
        MlShipmentOps(
            shipment_id=SHIPMENT_5990,
            order_id=ORDER_5990,
            logistic_type=logistic_type,
            raw_costs=raw_costs(SHIPMENT_5990) if costs is ... else costs,
        )
    )
    db.commit()

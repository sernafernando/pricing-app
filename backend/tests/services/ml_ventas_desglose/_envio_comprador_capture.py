"""Loads the REAL captures of the shipping the BUYER pays
(`tests/fixtures/ml_ventas_envio_comprador/`, captured 2026-10-07 from
production, personal buyer data stripped, structure untouched).

Never hand-write a `/shipments/{id}/costs` payload: a fixture written by hand
is an assumption about somebody else's API. The case keys are the captured
order ids; `pick` carries the logistic type and the `receiver_cost` as
captured (NOT trusted as the buyer's shipping: see `envio_comprador.py`, which
reads `payment.shipping_amount`).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import DateTime

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "ml_ventas_envio_comprador"
    / "buyer_shipping_capture_20261007.json"
)

# order_id of each captured case (the key of the fixture)
FULFILLMENT_990 = 2000018844749424  # buyer 990, charge shp_fulfillment 990 (+990 / -990)
CROSS_DOCKING = 2000018847750422  # buyer 4699.09, charge shp_cross_docking 14289.09
FULFILLMENT_3990 = 2000018847574430  # buyer 3990, plus a coupon_rebate charge
SELF_SERVICE_4990 = 2000018846969514  # buyer 4990, no discount, no shipping charge
SELF_SERVICE_PACK = 2000018846584294  # buyer 2216.30 + ratio discount 3773.70 (the #1415 bonificacion)
THREE_PAYMENTS = 2000018846999192  # 3 payments, one of them net 0
PACK_OTHER_SHIPMENT = 2000018814119064  # its shipment is stored under another order of the pack


def capture(order_id: int) -> Dict[str, Any]:
    return copy.deepcopy(json.loads(FIXTURE.read_text())[str(order_id)])


def _row(model, data: Dict[str, Any], **overrides):
    columns = {c.name: c for c in model.__table__.columns}
    values: Dict[str, Any] = {}
    for key, value in data.items():
        if key not in columns:
            continue
        if isinstance(value, str) and isinstance(columns[key].type, DateTime):
            value = datetime.fromisoformat(value)
        values[key] = value
    values.update(overrides)
    return model(**values)


def seed_case(
    db,
    case: int,
    *,
    order_id: Optional[int] = None,
    shipping_id: Any = ...,
    raw_costs: Any = ...,
    with_shipment: bool = True,
    seed_payments: bool = True,
) -> Dict[str, Any]:
    """Seeds one captured case. `order_id` seeds a SIBLING of the pack (its
    own payment ids; pass `with_shipment=False` so the shipment row, shared by
    the whole pack, is not inserted twice); `raw_costs=...` keeps the captured
    payload."""
    data = capture(case)["db"]
    oid = order_id or case
    order = data["orders"][0]
    ship_id = order["shipping_id"] if shipping_id is ... else shipping_id
    db.add(_row(MlOrdersOps, order, order_id=oid, shipping_id=ship_id, total_gauss=None))

    if seed_payments:
        offset = oid - case
        for item in data["items"]:
            db.add(_row(MlOrderItemOps, item, id=None, order_id=oid))
            db.add(
                MlOrderItemCosto(
                    order_id=oid,
                    item_id=item["item_id"],
                    costo_origen=Decimal("1000.00"),
                    moneda="ARS",
                    costo_unitario_ars=Decimal("1000.00"),
                    iva_pct=Decimal("21.00"),
                    precio_unitario=Decimal(str(item["unit_price"])),
                    fuente="sku",
                    producto_item_id=1,
                )
            )
        for payment in data["payments"]:
            db.add(_row(MlPaymentOps, payment, payment_id=payment["payment_id"] + offset, order_id=oid))
        for charge in data["payment_charges"]:
            db.add(_row(MlPaymentCharge, charge, id=None, payment_id=charge["payment_id"] + offset))

    if with_shipment and data["shipments"]:
        shipment = data["shipments"][0]
        overrides: Dict[str, Any] = {"shipment_id": ship_id, "order_id": oid}
        if raw_costs is not ...:
            overrides["raw_costs"] = raw_costs
        db.add(_row(MlShipmentOps, shipment, **overrides))
    db.commit()
    return data

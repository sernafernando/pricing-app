"""Loads the REAL capture of sale 2000018808335864 (pack 2000015364544817,
captured 2026-10-07 from production + the live ML API) into a test session.

Personal buyer data was stripped from the fixture; the structure is
untouched. Never hand-write a `/shipments/{id}/costs` payload: a fixture
written by hand is an assumption about somebody else's API.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import DateTime

from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "ml_ventas_bonificacion"
    / "flex_loyal_discount_capture_20261007.json"
)

ORDER_ID = 2000018808335864
PACK_ID = 2000015364544817
SHIPMENT_ID = 48178052704
GROSS = Decimal("8990")
NET_OF_IVA = Decimal("7429.75")  # 8990 / 1.21, HALF_UP


def capture() -> Dict[str, Any]:
    return copy.deepcopy(json.loads(FIXTURE.read_text()))


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


def seed_capture(
    db,
    *,
    order_id: int = ORDER_ID,
    shipping_id: Optional[int] = SHIPMENT_ID,
    pack_id: Optional[int] = PACK_ID,
    raw_costs: Any = ...,
    logistic_type: Optional[str] = None,
    with_shipment: bool = True,
    with_cost: bool = True,
    with_flex_label: bool = True,
    seed_shared_rows: bool = True,
) -> Dict[str, Any]:
    """Seeds one order of the capture. `raw_costs=...` keeps the captured
    payload; pass None / another payload to override it. A SECOND order of
    the same pack passes `order_id=<other>` and `seed_shared_rows=False`
    (the shipment and its label are one row shared by the whole pack)."""
    data = capture()["db"]
    order = data["orders"][0]
    db.add(_row(MlOrdersOps, order, order_id=order_id, shipping_id=shipping_id, pack_id=pack_id, total_gauss=None))

    item = data["items"][0]
    db.add(_row(MlOrderItemOps, item, id=None, order_id=order_id))
    payment = data["payments"][0]
    payment_id = payment["payment_id"] + (order_id - ORDER_ID)
    db.add(_row(MlPaymentOps, payment, payment_id=payment_id, order_id=order_id))
    for charge in data["payment_charges"]:
        db.add(_row(MlPaymentCharge, charge, id=None, payment_id=payment_id))
    if with_cost:
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id=item["item_id"],
                costo_origen=Decimal("6000.00"),
                moneda="ARS",
                costo_unitario_ars=Decimal("6000.00"),
                iva_pct=Decimal("21.00"),
                precio_unitario=Decimal(str(item["unit_price"])),
                fuente="sku",
                producto_item_id=1,
            )
        )

    if with_shipment and seed_shared_rows:
        shipment = data["shipments"][0]
        overrides: Dict[str, Any] = {"shipment_id": shipping_id, "order_id": order_id}
        if raw_costs is not ...:
            overrides["raw_costs"] = raw_costs
        if logistic_type is not None:
            overrides["logistic_type"] = logistic_type
        db.add(_row(MlShipmentOps, shipment, **overrides))
        if with_flex_label:
            db.add(Logistica(id=1, nombre="Super Express"))
            db.add(
                EtiquetaEnvio(
                    shipping_id=str(shipping_id),
                    fecha_envio=date(2026, 10, 5),
                    logistica_id=1,
                    costo_override=Decimal("1000.00"),
                )
            )
    db.commit()
    return data

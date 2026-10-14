"""RED/GREEN -- one shipping charge, one shipping line.

ML reports the SAME shipping charge through two channels: the payment's
`shp_*` charge and the billing sweep's CXD/CFF/CSSTEC row. Order
2000018960873512 (captured from production 2026-10-14,
`tests/fixtures/ml_charges/envio_duplicado_capture_20261014.json`) carries
`shp_cross_docking` 9590 on its payment AND a CXD "Cargo por envíos de
Mercado Libre" 9590 bridged to it, and the drawer showed both:

    (−) Envíos (Colecta)  -$ 9.590,00
    (−) Envios            -$ 9.590,00

18,048 production orders carry both. The billing row exists in the
breakdown for orders whose payments carry NO `shp_*` charge (only 5,075 of
12,528 payments carry one), so it stays -- as the fallback, never on top.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import CONCEPTO_ENVIOS, compute_breakdown

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "ml_charges" / "envio_duplicado_capture_20261014.json"

COLECTA = "Envíos (Colecta)"
SHIPPING_LABELS = {COLECTA, "Envíos (Full)", "Envíos (Flex — cargo ML)", CONCEPTO_ENVIOS}


def _capture() -> dict:
    return json.loads(FIXTURE.read_text())


def _money(value) -> Decimal:
    return Decimal(str(value))


def _order(db, order_id: int, pack_id=None, shipping_id=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=datetime(2026, 10, 13, tzinfo=timezone.utc),
            seller_id=999,
            shipping_id=shipping_id,
        )
    )


def _load_payment(db, payment: dict, *, order_id=None, payment_id=None, drop_shipping=False) -> None:
    payment_id = payment_id or payment["payment_id"]
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id or payment["order_id"],
            status=payment["status"],
            transaction_amount=_money(payment["transaction_amount"]),
            shipping_amount=_money(payment["shipping_amount"]),
            net_received_amount=_money(payment["net_received_amount"]),
        )
    )
    db.flush()
    for charge in payment["charges"]:
        if drop_shipping and charge["name"].startswith("shp_"):
            continue
        db.add(
            MlPaymentCharge(
                payment_id=payment_id,
                name=charge["name"],
                type=charge["type"],
                amount=_money(charge["amount"]),
                refunded=_money(charge["refunded"]),
            )
        )


def _load_billing(db, billing: dict, order_ids, *, detail_id=None) -> None:
    detail_id = detail_id or billing["detail_id"]
    db.add(
        MlBillingCharge(
            detail_id=detail_id,
            detail_type=billing["detail_type"],
            detail_sub_type=billing["detail_sub_type"],
            amount=_money(billing["amount"]),
            document_id=billing["document_id"],
            raw_detail=billing["raw_detail"],
        )
    )
    db.flush()
    for order_id in order_ids:
        db.add(MlBillingChargeOrder(detail_id=detail_id, order_id=order_id))


def _shipping_lines(result) -> dict:
    return {line.concepto: line.monto for line in result.lines if line.concepto in SHIPPING_LABELS}


class TestShippingChargeReportedTwiceIsCountedOnce:
    def test_captured_order_shows_one_colecta_line_and_no_generic_envios(self, db) -> None:
        capture = _capture()
        order_id = capture["payment"]["order_id"]
        shipping_id = int(capture["billing_charge"]["raw_detail"]["shipping_info"]["shipping_id"])
        _order(db, order_id, shipping_id=shipping_id)
        _load_payment(db, capture["payment"])
        _load_billing(db, capture["billing_charge"], [order_id])
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert _shipping_lines(result) == {COLECTA: Decimal("9590.00")}
        # The net never read shipping lines -- it stays what ML deposited.
        assert result.neto_depositado == Decimal("1183340.22")
        assert result.incompleto is False

    def test_pack_sibling_payment_shp_charge_suppresses_the_shared_billing_row(self, db) -> None:
        """The billing row is bridged to every order in the pack; the `shp_*`
        charge sits on one sibling's payment. Still one charge, one line."""
        capture = _capture()
        pack_id, order_a, order_b = 9100, 9101, 9102
        _order(db, order_a, pack_id=pack_id, shipping_id=48248844452)
        _order(db, order_b, pack_id=pack_id, shipping_id=48248844452)
        _load_payment(db, capture["payment"], order_id=order_a, payment_id=91)
        _load_payment(db, capture["payment"], order_id=order_b, payment_id=92, drop_shipping=True)
        _load_billing(db, capture["billing_charge"], [order_a, order_b])
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        assert _shipping_lines(result) == {COLECTA: Decimal("9590.00")}


class TestBillingShippingStaysAsTheFallback:
    def test_order_with_only_the_billing_charge_keeps_the_envios_line(self, db) -> None:
        capture = _capture()
        order_id = capture["payment"]["order_id"]
        _order(db, order_id, shipping_id=48248844452)
        _load_payment(db, capture["payment"], drop_shipping=True)
        _load_billing(db, capture["billing_charge"], [order_id])
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert _shipping_lines(result) == {CONCEPTO_ENVIOS: Decimal("9590.00")}
        assert result.incompleto is False

    def test_pack_without_shp_charges_keeps_one_billing_line(self, db) -> None:
        capture = _capture()
        pack_id, order_a, order_b = 9200, 9201, 9202
        _order(db, order_a, pack_id=pack_id, shipping_id=1)
        _order(db, order_b, pack_id=pack_id, shipping_id=1)
        _load_payment(db, capture["payment"], order_id=order_a, payment_id=93, drop_shipping=True)
        _load_payment(db, capture["payment"], order_id=order_b, payment_id=94, drop_shipping=True)
        _load_billing(db, capture["billing_charge"], [order_a, order_b])
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        assert _shipping_lines(result) == {CONCEPTO_ENVIOS: Decimal("9590.00")}

    def test_billing_row_of_an_order_without_shp_survives_a_sibling_that_has_one(self, db) -> None:
        """Suppression is per billing row, by the orders it is bridged to --
        never group-wide. Order B's own billing charge is B's only shipping."""
        capture = _capture()
        order_a, order_b = 9301, 9302
        _order(db, order_a, shipping_id=1)
        _order(db, order_b, shipping_id=2)
        _load_payment(db, capture["payment"], order_id=order_a, payment_id=95)
        _load_payment(db, capture["payment"], order_id=order_b, payment_id=96, drop_shipping=True)
        _load_billing(db, capture["billing_charge"], [order_a], detail_id="D-A")
        _load_billing(db, capture["billing_charge"], [order_b], detail_id="D-B")
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        assert _shipping_lines(result) == {COLECTA: Decimal("9590.00"), CONCEPTO_ENVIOS: Decimal("9590.00")}

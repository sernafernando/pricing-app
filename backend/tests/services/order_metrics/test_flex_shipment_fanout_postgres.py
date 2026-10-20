"""Every order sharing a Flex shipment is recomputed when the shipment's
membership or payments change (flex-envio-comprador review).

The Flex buyer-paid shipping, the Flex bonificación and `EnvioFlexDeduccion`
all divide the shipment's amount by the number of orders sharing its
`shipping_id`, read at compute time. If order A is computed alone it stores
the WHOLE amount; when sibling B lands, A must be recomputed too, or the pack
counts the amount 1.5 times. These tests replay the drain over the real dirty
queue (real Postgres triggers) and check the stored shares add up to ONE
shipment. Real Postgres only: the fan-out lives in plpgsql triggers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict

import pytest
from sqlalchemy import text

from app.services.ml_ventas_desglose.bonificacion_flex import resolve_bonificacion_flex_by_order_ids
from app.services.ml_ventas_desglose.envio_comprador import resolve_envio_comprador_flex_by_order_ids
from app.services.ml_ventas_desglose.iva import IVA_ML_DIVISOR
from tests.services.ml_ventas_desglose._flex_receiver_capture import raw_costs, seller_id

PACK_SHIPMENT = 48195392397  # captured: cost_details 2216.30, sender discount 599
ORDER_A, ORDER_B, ORDER_C = 340001, 340002, 340003
PAYMENT_A = 940001
OTHER_SHIPMENT = 800000340


def _insert_order(session, order_id: int, shipping_id: int) -> None:
    session.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, shipping_id) "
            "VALUES (:order_id, :seller_id, 'paid', :ts, :ts, :shipping_id)"
        ),
        {
            "order_id": order_id,
            "seller_id": seller_id(PACK_SHIPMENT),
            "ts": datetime(2026, 10, 19, tzinfo=timezone.utc),
            "shipping_id": shipping_id,
        },
    )


def _insert_payment(session, payment_id: int, order_id: int, shipping_amount: float = 0.0) -> None:
    session.execute(
        text(
            "INSERT INTO ml_payments_ops (payment_id, order_id, status, shipping_amount, net_received_amount) "
            "VALUES (:payment_id, :order_id, 'approved', :shipping_amount, 1000)"
        ),
        {"payment_id": payment_id, "order_id": order_id, "shipping_amount": shipping_amount},
    )


def _dirty(session) -> set:
    return {row[0] for row in session.execute(text("SELECT order_id FROM ml_order_metrics_dirty"))}


def _clear_dirty(session) -> None:
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.commit()


def _drain(session, stored: Dict[int, Dict[str, Decimal]]) -> None:
    """What `order_metrics.drain` does for these figures: recompute every
    DIRTY order and overwrite its stored share; clean orders keep theirs."""
    dirty = sorted(_dirty(session))
    envio = resolve_envio_comprador_flex_by_order_ids(session, dirty, IVA_ML_DIVISOR)
    bonificacion = resolve_bonificacion_flex_by_order_ids(session, dirty, IVA_ML_DIVISOR)
    for order_id in dirty:
        stored[order_id] = {
            "envio": envio[order_id].bruto if order_id in envio else Decimal("0"),
            "bonificacion": bonificacion[order_id].bruto if order_id in bonificacion else Decimal("0"),
        }
    _clear_dirty(session)


@pytest.fixture()
def session(pg_order_metrics_triggers_db):
    session = pg_order_metrics_triggers_db
    _clear_dirty(session)
    yield session
    session.rollback()
    session.execute(text("DELETE FROM ml_payments_ops WHERE payment_id = :p"), {"p": PAYMENT_A})
    session.execute(
        text("DELETE FROM ml_shipments_ops WHERE shipment_id IN (:a, :b)"), {"a": PACK_SHIPMENT, "b": OTHER_SHIPMENT}
    )
    session.execute(
        text("DELETE FROM ml_orders_ops WHERE order_id IN (:a, :b, :c)"), {"a": ORDER_A, "b": ORDER_B, "c": ORDER_C}
    )
    session.commit()
    _clear_dirty(session)


@pytest.mark.postgres
class TestASiblingArrivingLater:
    def test_both_orders_end_at_half_after_the_drain(self, session) -> None:
        """A is computed alone (whole amount), then B arrives. MUTATION: the
        orders trigger without its INSERT shipping fan-out leaves A at 100%."""
        _insert_order(session, ORDER_A, PACK_SHIPMENT)
        session.execute(
            text(
                "INSERT INTO ml_shipments_ops (shipment_id, order_id, logistic_type, raw_costs) "
                "VALUES (:shipment_id, :order_id, 'self_service', CAST(:raw_costs AS jsonb))"
            ),
            {"shipment_id": PACK_SHIPMENT, "order_id": ORDER_A, "raw_costs": json.dumps(raw_costs(PACK_SHIPMENT))},
        )
        session.commit()
        stored: Dict[int, Dict[str, Decimal]] = {}
        _drain(session, stored)
        assert stored[ORDER_A] == {"envio": Decimal("2216.30"), "bonificacion": Decimal("599.00")}

        _insert_order(session, ORDER_B, PACK_SHIPMENT)
        session.commit()
        _drain(session, stored)

        assert stored[ORDER_A]["envio"] + stored[ORDER_B]["envio"] == Decimal("2216.30")
        assert stored[ORDER_A]["envio"] == stored[ORDER_B]["envio"] == Decimal("1108.15")
        assert stored[ORDER_A]["bonificacion"] + stored[ORDER_B]["bonificacion"] == Decimal("599.00")

    def test_moving_an_order_onto_the_shipment_recomputes_the_others(self, session) -> None:
        """UPDATE of `shipping_id` (C moves onto the pack shipment)."""
        _insert_order(session, ORDER_A, PACK_SHIPMENT)
        _insert_order(session, ORDER_C, OTHER_SHIPMENT)
        session.commit()
        _clear_dirty(session)

        session.execute(
            text("UPDATE ml_orders_ops SET shipping_id = :s WHERE order_id = :o"), {"s": PACK_SHIPMENT, "o": ORDER_C}
        )
        session.commit()

        assert {ORDER_A, ORDER_C} <= _dirty(session)


@pytest.mark.postgres
class TestPaymentFanOutNeverFails:
    """The payment fan-out joins the payment's own order to itself, so its
    ids array is deduplicated before `order_metrics_enqueue`."""

    def test_a_pack_payment_update_enqueues_each_sibling_once(self, session) -> None:
        _insert_order(session, ORDER_A, PACK_SHIPMENT)
        _insert_order(session, ORDER_B, PACK_SHIPMENT)
        _insert_payment(session, PAYMENT_A, ORDER_A)
        session.commit()
        _clear_dirty(session)

        session.execute(text("UPDATE ml_payments_ops SET shipping_amount = 10 WHERE payment_id = :p"), {"p": PAYMENT_A})
        session.commit()

        assert _dirty(session) == {ORDER_A, ORDER_B}

    def test_an_order_id_moving_update_enqueues_both_shipments(self, session) -> None:
        _insert_order(session, ORDER_A, PACK_SHIPMENT)
        _insert_order(session, ORDER_B, PACK_SHIPMENT)
        _insert_order(session, ORDER_C, OTHER_SHIPMENT)
        _insert_payment(session, PAYMENT_A, ORDER_A)
        session.commit()
        _clear_dirty(session)

        session.execute(
            text("UPDATE ml_payments_ops SET order_id = :o WHERE payment_id = :p"), {"o": ORDER_C, "p": PAYMENT_A}
        )
        session.commit()

        assert _dirty(session) == {ORDER_A, ORDER_B, ORDER_C}

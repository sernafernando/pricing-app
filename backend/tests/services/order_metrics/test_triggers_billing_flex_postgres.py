"""ml-billing-balance PR 9-i -- an order's stored Total Gauss is recomputed when its
billing BFLX line lands (the Flex bonification reads billing from PR 9-i-2 on; see
`bonificacion_flex.py`). Postgres-only: it asserts what plpgsql triggers do.

The billing tables are created here with only the columns the trigger reads
(`detail_id`, `detail_sub_type`, `amount`; the bridge's `order_id`) so this file does
not depend on the JSONB/SQLite type patching of the shared fixtures.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.order_metrics.triggers_billing_flex import (
    create_billing_flex_triggers,
    drop_billing_flex_triggers,
)

_DDL = (
    "CREATE TABLE IF NOT EXISTS ml_billing_charges (detail_id VARCHAR(60) PRIMARY KEY, "
    "detail_sub_type VARCHAR(60), amount NUMERIC(14, 2))",
    "CREATE TABLE IF NOT EXISTS ml_billing_charge_orders (id SERIAL PRIMARY KEY, detail_id VARCHAR(60) NOT NULL "
    "REFERENCES ml_billing_charges (detail_id), order_id BIGINT NOT NULL, UNIQUE (detail_id, order_id))",
)
_ORDER, _SIBLING, _STRANGER = 330101, 330102, 330103
_SHIPMENT = 800000101


def _dirty(session) -> dict:
    rows = session.execute(text("SELECT order_id, reason FROM ml_order_metrics_dirty")).all()
    return {r.order_id: r.reason for r in rows}


@pytest.fixture()
def slate(pg_order_metrics_triggers_db):
    session = pg_order_metrics_triggers_db
    # Created here only when absent, and dropped only by the run that created them.
    created = not session.execute(text("SELECT to_regclass('ml_billing_charges')")).scalar()
    for statement in _DDL:
        session.execute(text(statement))
    create_billing_flex_triggers(session.connection())
    for oid, shipment in ((_ORDER, _SHIPMENT), (_SIBLING, _SHIPMENT), (_STRANGER, None)):
        session.execute(
            text(
                "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, shipping_id) "
                "VALUES (:oid, 999, 'paid', now(), now(), :sid)"
            ),
            {"oid": oid, "sid": shipment},
        )
    session.commit()
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.commit()
    yield session
    drop_billing_flex_triggers(session.connection())
    session.execute(text("DELETE FROM ml_billing_charge_orders WHERE order_id IN (330101, 330102, 330103)"))
    session.execute(text("DELETE FROM ml_billing_charges WHERE detail_id LIKE 'T9I-%'"))
    if created:
        session.execute(text("DROP TABLE ml_billing_charge_orders, ml_billing_charges"))
    session.execute(text("DELETE FROM ml_orders_ops WHERE seller_id = 999"))
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.commit()


def _charge(session, detail_id: str, sub_type: str, amount: str = "-8990.00") -> None:
    session.execute(
        text("INSERT INTO ml_billing_charges (detail_id, detail_sub_type, amount) VALUES (:d, :s, :a)"),
        {"d": detail_id, "s": sub_type, "a": amount},
    )


def _link(session, detail_id: str, order_id: int) -> None:
    session.execute(
        text(
            "INSERT INTO ml_billing_charge_orders (detail_id, order_id) VALUES (:d, :o) "
            "ON CONFLICT (detail_id, order_id) DO NOTHING"
        ),
        {"d": detail_id, "o": order_id},
    )
    session.commit()


@pytest.mark.postgres
class TestBflxLandingRecomputesTheOrder:
    def test_linking_a_bflx_enqueues_the_order_and_its_shipment_siblings(self, slate) -> None:
        _charge(slate, "T9I-1", "BFLX")
        _link(slate, "T9I-1", _ORDER)

        assert _dirty(slate) == {_ORDER: "ml_billing_flex", _SIBLING: "ml_billing_flex"}

    def test_linking_any_other_sub_type_enqueues_nothing(self, slate) -> None:
        _charge(slate, "T9I-2", "CFLX", "649.00")
        _link(slate, "T9I-2", _ORDER)

        assert _dirty(slate) == {}

    def test_a_bflx_linked_to_an_order_without_shipment_enqueues_only_that_order(self, slate) -> None:
        _charge(slate, "T9I-3", "BFLX")
        _link(slate, "T9I-3", _STRANGER)

        assert set(_dirty(slate)) == {_STRANGER}

    def test_a_new_link_enqueues_only_its_own_order_not_the_charges_other_links(self, slate) -> None:
        _charge(slate, "T9I-6", "BFLX")
        _link(slate, "T9I-6", _ORDER)
        slate.execute(text("DELETE FROM ml_order_metrics_dirty"))
        slate.commit()

        _link(slate, "T9I-6", _STRANGER)

        assert set(_dirty(slate)) == {_STRANGER}

    def test_a_charge_that_stops_being_bflx_recomputes_its_orders(self, slate) -> None:
        _charge(slate, "T9I-7", "BFLX")
        _link(slate, "T9I-7", _ORDER)
        slate.execute(text("DELETE FROM ml_order_metrics_dirty"))
        slate.commit()

        slate.execute(text("UPDATE ml_billing_charges SET detail_sub_type = 'CFLX' WHERE detail_id = 'T9I-7'"))
        slate.commit()

        assert set(_dirty(slate)) == {_ORDER, _SIBLING}

    def test_removing_a_bflx_link_recomputes_its_order_and_siblings(self, slate) -> None:
        _charge(slate, "T9I-8", "BFLX")
        _link(slate, "T9I-8", _ORDER)
        slate.execute(text("DELETE FROM ml_order_metrics_dirty"))
        slate.commit()

        slate.execute(text("DELETE FROM ml_billing_charge_orders WHERE detail_id = 'T9I-8'"))
        slate.commit()

        assert set(_dirty(slate)) == {_ORDER, _SIBLING}

    def test_a_changed_amount_recomputes_but_an_identical_rewrite_does_not(self, slate) -> None:
        _charge(slate, "T9I-4", "BFLX")
        _link(slate, "T9I-4", _ORDER)
        slate.execute(text("DELETE FROM ml_order_metrics_dirty"))
        slate.commit()

        slate.execute(text("UPDATE ml_billing_charges SET amount = -8990.00 WHERE detail_id = 'T9I-4'"))
        slate.commit()
        assert _dirty(slate) == {}

        slate.execute(text("UPDATE ml_billing_charges SET amount = -9000.00 WHERE detail_id = 'T9I-4'"))
        slate.commit()
        assert set(_dirty(slate)) == {_ORDER, _SIBLING}

    def test_relinking_an_existing_pair_is_a_no_op(self, slate) -> None:
        _charge(slate, "T9I-5", "BFLX")
        _link(slate, "T9I-5", _ORDER)
        slate.execute(text("DELETE FROM ml_order_metrics_dirty"))
        slate.commit()

        _link(slate, "T9I-5", _ORDER)

        assert _dirty(slate) == {}

"""The tax treatment enqueue trigger (ventas-ml-impuestos-informativos S2): a version recomputes the stored sales of
its period that carry its charge name. Real Postgres only (statement triggers with transition tables)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from tests.services.order_metrics.test_triggers_config_postgres import _clear_dirty, _dirty_row, _insert_order

pytestmark = pytest.mark.postgres

SOBRETASA = "tax_withholding_sirtac_sobretasa-jujuy"
IN_PERIOD, BEFORE, OTHER_TAX = 530001, 530002, 530003


@pytest.fixture()
def sales(pg_order_metrics_config_triggers_db):
    """Three sales: one in September with the surcharge, one in August with it, one in September without it."""
    session = pg_order_metrics_config_triggers_db
    for order_id, sold_on, charge in (
        (IN_PERIOD, datetime(2026, 9, 10, tzinfo=timezone.utc), SOBRETASA),
        (BEFORE, datetime(2026, 8, 10, tzinfo=timezone.utc), SOBRETASA),
        (OTHER_TAX, datetime(2026, 9, 10, tzinfo=timezone.utc), "tax_withholding_sirtac-caba"),
    ):
        _insert_order(session, order_id, date_created=sold_on)
        session.execute(
            text("INSERT INTO ml_payments_ops (payment_id, order_id, status) VALUES (:p, :o, 'approved')"),
            {"p": order_id * 10, "o": order_id},
        )
        session.execute(
            text("INSERT INTO ml_payment_charges (payment_id, name, type, amount) VALUES (:p, :n, 'tax', 300)"),
            {"p": order_id * 10, "n": charge},
        )
    session.commit()
    _clear_dirty(session)
    yield session
    session.rollback()
    session.execute(text("DELETE FROM ml_venta_impuesto_tratamiento"))
    session.execute(
        text("DELETE FROM ml_payment_charges WHERE payment_id = ANY(:p)"), {"p": [5300010, 5300020, 5300030]}
    )
    session.execute(text("DELETE FROM ml_payments_ops WHERE payment_id = ANY(:p)"), {"p": [5300010, 5300020, 5300030]})
    session.execute(
        text("DELETE FROM ml_orders_ops WHERE order_id = ANY(:ids)"), {"ids": [IN_PERIOD, BEFORE, OTHER_TAX]}
    )
    session.commit()
    _clear_dirty(session)


def _enqueued(session) -> set:
    return {o for o in (IN_PERIOD, BEFORE, OTHER_TAX) if _dirty_row(session, o) is not None}


def test_a_new_version_recomputes_its_period_sales_with_that_charge(sales) -> None:
    sales.execute(
        text("INSERT INTO ml_venta_impuesto_tratamiento (charge_name, informativo, fecha_desde) VALUES (:n, true, :d)"),
        {"n": SOBRETASA, "d": date(2026, 9, 1)},
    )
    sales.commit()

    assert _enqueued(sales) == {IN_PERIOD}
    assert _dirty_row(sales, IN_PERIOD).reason == "impuesto_tratamiento_insert"


def test_moving_a_start_back_recomputes_the_sales_it_now_covers(sales) -> None:
    sales.execute(
        text("INSERT INTO ml_venta_impuesto_tratamiento (charge_name, informativo, fecha_desde) VALUES (:n, true, :d)"),
        {"n": SOBRETASA, "d": date(2026, 9, 1)},
    )
    sales.commit()
    _clear_dirty(sales)

    sales.execute(text("UPDATE ml_venta_impuesto_tratamiento SET fecha_desde = :d"), {"d": date(2026, 8, 1)})
    sales.commit()

    assert _enqueued(sales) == {IN_PERIOD, BEFORE}


def test_an_identical_rewrite_recomputes_nothing(sales) -> None:
    sales.execute(
        text("INSERT INTO ml_venta_impuesto_tratamiento (charge_name, informativo, fecha_desde) VALUES (:n, true, :d)"),
        {"n": SOBRETASA, "d": date(2026, 9, 1)},
    )
    sales.commit()
    _clear_dirty(sales)

    sales.execute(text("UPDATE ml_venta_impuesto_tratamiento SET informativo = informativo"))
    sales.commit()

    assert _enqueued(sales) == set()


def test_deleting_a_version_recomputes_the_sales_it_covered(sales) -> None:
    sales.execute(
        text("INSERT INTO ml_venta_impuesto_tratamiento (charge_name, informativo, fecha_desde) VALUES (:n, true, :d)"),
        {"n": SOBRETASA, "d": date(2026, 9, 1)},
    )
    sales.commit()
    _clear_dirty(sales)

    sales.execute(text("DELETE FROM ml_venta_impuesto_tratamiento"))
    sales.commit()

    assert _enqueued(sales) == {IN_PERIOD}

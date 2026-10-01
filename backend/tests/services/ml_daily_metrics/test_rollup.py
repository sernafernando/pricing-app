"""ODD `metricas-ml-tablero` T2: the daily rollup
(`ml_product_daily_metrics`, product x MLA x accreditation day).

SUMS only, never percentages. Kept current by `store_order_metrics` -- the
SAME short transaction that stores an order's metrics and its group's --
recomputing every affected (MLA, day) bucket FROM SOURCE, so a re-store
never double counts and a sale that moved day (or got cancelled) leaves its
old bucket instead of lingering there.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_daily_metrics import MlProductDailyMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_daily_metrics.rollup import refresh_rollup
from app.services.order_metrics.store import store_order_metrics
from app.services.order_metrics.types import GaussStatus, OrderMetrics

# 01:30 UTC on the 21st is still the 20th in Buenos Aires (UTC-3).
ACCREDITED = datetime(2026, 9, 21, 1, 30, tzinfo=timezone.utc)
DAY = date(2026, 9, 20)


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _order(db, order_id: int, *, pack_id=None, status="paid", covered=None, accredited=ACCREDITED) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status=status,
            covered_by_marketplace=covered,
            ml_last_updated=accredited or ACCREDITED,
            date_created=accredited or ACCREDITED,
            seller_id=999,
            currency_id="ARS",
        )
    )
    if accredited is not None:
        db.add(MlPaymentOps(payment_id=order_id * 10, order_id=order_id, status="approved", date_approved=accredited))
    db.flush()


def _item(db, order_id: int, mla: str, *, qty: int, price: str, producto: int | None, costo: str = "100") -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=mla, quantity=qty, unit_price=Decimal(price)))
    if producto is not None:
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id=mla,
                variation_id=None,
                costo_origen=Decimal(costo),
                moneda="ARS",
                costo_unitario_ars=Decimal(costo),
                iva_pct=21,
                precio_unitario=Decimal(price),
                fuente="test",
                producto_item_id=producto,
            )
        )
    db.flush()


def _metrics(order_id: int, total_gauss: str | None = "50.00", costo: str | None = "200.00", status=GaussStatus.OK):
    tg = Decimal(total_gauss) if total_gauss is not None else None
    cm = Decimal(costo) if costo is not None else None
    return OrderMetrics(
        order_id=order_id,
        neto=Decimal("300.00"),
        neto_sin_iva=Decimal("250.00"),
        iva_reconcilia=True,
        costo_mercaderia=cm,
        total_gauss=tg,
        markup_pct=(tg / cm * 100) if tg is not None and cm else None,
        gauss_status=status,
        provisional_falta=None,
        unresolved_reason=None,
        formula_version=2,
        computed_at=datetime.now(timezone.utc),
    )


def _rows(db):
    return {(r.product_item_id, r.mla, r.day): r for r in db.query(MlProductDailyMetrics).all()}


class TestOneOrder:
    def test_storing_an_order_writes_its_bucket_on_the_accreditation_day(self, db):
        _order(db, 2000010000000001)
        _item(db, 2000010000000001, "MLA1", qty=2, price="150.00", producto=11)

        store_order_metrics(db, {2000010000000001: _metrics(2000010000000001)})

        row = _rows(db)[(11, "MLA1", DAY)]
        assert row.units == 2
        assert row.gross_ars == Decimal("300.00")
        assert row.total_gauss == Decimal("50.00")
        assert row.costo == Decimal("200.00")
        assert row.orders == 1
        assert row.unresolved_orders == 0
        assert row.last_sale_at.replace(tzinfo=timezone.utc) == ACCREDITED

    def test_storing_twice_never_double_counts(self, db):
        _order(db, 101)
        _item(db, 101, "MLA1", qty=1, price="100.00", producto=11)

        store_order_metrics(db, {101: _metrics(101)})
        store_order_metrics(db, {101: _metrics(101)})

        assert _rows(db)[(11, "MLA1", DAY)].units == 1
        assert _rows(db)[(11, "MLA1", DAY)].orders == 1

    def test_an_order_without_usable_metrics_counts_units_but_not_money(self, db):
        _order(db, 102)
        _item(db, 102, "MLA1", qty=3, price="100.00", producto=11)

        store_order_metrics(db, {102: _metrics(102, total_gauss=None, costo=None, status=GaussStatus.UNRESOLVED)})

        row = _rows(db)[(11, "MLA1", DAY)]
        assert row.units == 3
        assert row.total_gauss == Decimal("0")
        assert row.costo == Decimal("0")
        assert row.unresolved_orders == 1

    def test_an_item_with_no_frozen_cost_lands_under_product_zero(self, db):
        _order(db, 103)
        _item(db, 103, "MLA9", qty=1, price="100.00", producto=None)

        store_order_metrics(db, {103: _metrics(103, total_gauss=None, costo=None, status=GaussStatus.UNRESOLVED)})

        assert (0, "MLA9", DAY) in _rows(db)

    def test_a_sale_with_no_accredited_money_is_in_no_day(self, db):
        _order(db, 104, accredited=None)
        _item(db, 104, "MLA1", qty=1, price="100.00", producto=11)

        store_order_metrics(db, {104: _metrics(104)})

        assert _rows(db) == {}


class TestMultiItemAllocation:
    def test_total_gauss_and_cost_split_by_each_items_frozen_cost_share(self, db):
        """Item A: 1 x 300 frozen cost, item B: 2 x 50 -> weights 300 vs 100,
        so A takes 3/4 of the order's Total Gauss and cost, B 1/4."""
        _order(db, 105)
        _item(db, 105, "MLA_A", qty=1, price="500.00", producto=21, costo="300")
        _item(db, 105, "MLA_B", qty=2, price="80.00", producto=22, costo="50")

        store_order_metrics(db, {105: _metrics(105, total_gauss="80.00", costo="400.00")})

        rows = _rows(db)
        assert rows[(21, "MLA_A", DAY)].total_gauss == Decimal("60.00")
        assert rows[(21, "MLA_A", DAY)].costo == Decimal("300.00")
        assert rows[(22, "MLA_B", DAY)].total_gauss == Decimal("20.00")
        assert rows[(22, "MLA_B", DAY)].costo == Decimal("100.00")
        assert rows[(22, "MLA_B", DAY)].units == 2
        assert rows[(22, "MLA_B", DAY)].gross_ars == Decimal("160.00")
        # Both buckets count the order once each.
        assert rows[(21, "MLA_A", DAY)].orders == rows[(22, "MLA_B", DAY)].orders == 1


class TestSelfHealing:
    def test_a_sale_whose_day_moved_leaves_its_old_bucket(self, db):
        _order(db, 106)
        _item(db, 106, "MLA1", qty=1, price="100.00", producto=11)
        store_order_metrics(db, {106: _metrics(106)})
        assert (11, "MLA1", DAY) in _rows(db)

        # A later relevant payment moves the accreditation (MAX) to the 25th.
        db.add(
            MlPaymentOps(
                payment_id=1062,
                order_id=106,
                status="approved",
                date_approved=datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc),
            )
        )
        db.flush()
        store_order_metrics(db, {106: _metrics(106)})

        rows = _rows(db)
        assert (11, "MLA1", DAY) not in rows
        assert rows[(11, "MLA1", date(2026, 9, 25))].units == 1

    def test_a_cancelled_sale_leaves_the_bucket(self, db):
        _order(db, 107)
        _item(db, 107, "MLA1", qty=1, price="100.00", producto=11)
        store_order_metrics(db, {107: _metrics(107)})

        db.query(MlOrdersOps).filter_by(order_id=107).update({"status": "cancelled"})
        db.flush()
        store_order_metrics(db, {107: _metrics(107)})

        assert _rows(db) == {}

    def test_a_cancellation_covered_by_ml_still_counts(self, db):
        _order(db, 108, status="cancelled", covered=True)
        _item(db, 108, "MLA1", qty=1, price="100.00", producto=11)

        store_order_metrics(db, {108: _metrics(108)})

        assert _rows(db)[(11, "MLA1", DAY)].units == 1

    def test_the_other_orders_of_the_bucket_stay_counted(self, db):
        _order(db, 109)
        _order(db, 110)
        _item(db, 109, "MLA1", qty=1, price="100.00", producto=11)
        _item(db, 110, "MLA1", qty=4, price="100.00", producto=11)
        store_order_metrics(db, {109: _metrics(109), 110: _metrics(110)})
        assert _rows(db)[(11, "MLA1", DAY)].units == 5

        # Re-storing ONE of them recomputes the bucket from source.
        store_order_metrics(db, {109: _metrics(109)})

        assert _rows(db)[(11, "MLA1", DAY)].units == 5
        assert _rows(db)[(11, "MLA1", DAY)].orders == 2

    def test_refresh_rewrites_a_tampered_bucket(self, db):
        _order(db, 111)
        _item(db, 111, "MLA1", qty=1, price="100.00", producto=11)
        store_order_metrics(db, {111: _metrics(111)})
        db.query(MlProductDailyMetrics).update({"units": 999})
        db.flush()

        refresh_rollup(db, {("MLA1", DAY)})

        assert _rows(db)[(11, "MLA1", DAY)].units == 1


class TestPacks:
    def test_a_pack_lands_on_its_group_day(self, db):
        """The day is the GROUP's (MAX over all members), like Ventas ML."""
        _order(db, 112, pack_id=900)
        _order(db, 113, pack_id=900, accredited=datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc))
        _item(db, 112, "MLA1", qty=1, price="100.00", producto=11)
        _item(db, 113, "MLA2", qty=1, price="100.00", producto=12)

        store_order_metrics(db, {112: _metrics(112), 113: _metrics(113)})

        rows = _rows(db)
        assert set(rows) == {(11, "MLA1", date(2026, 9, 22)), (12, "MLA2", date(2026, 9, 22))}

    def test_never_commits(self, db):
        _order(db, 114)
        _item(db, 114, "MLA1", qty=1, price="100.00", producto=11)
        db.commit()

        store_order_metrics(db, {114: _metrics(114)})
        db.rollback()

        assert _rows(db) == {}

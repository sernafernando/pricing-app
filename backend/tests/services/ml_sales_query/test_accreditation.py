"""RED/GREEN tests for the single "day of this sale" resolver
(`ml_sales_query/accreditation.py`, ODD `ventas-ml-dia-por-acreditacion`).

The decisive case: a sale created on day A whose last relevant
accreditation is on day B must appear in B's range and NOT in A's --
`TestFilterDayIsAccreditationNotCreation`. And explicitly MAX vs MIN for a
pack whose members accredit on two different days --
`TestPackDayIsTheLatestMember`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_sales_query.filters import SalesFilter, build_scope


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _order(db, order_id: int, *, pack_id=None, date_created=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=date_created or datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_created=date_created or datetime(2026, 1, 1, tzinfo=timezone.utc),
            seller_id=999,
            total_amount=100,
            paid_amount=100,
            currency_id="ARS",
        )
    )


def _payment(db, *, payment_id: int, order_id: int, status: str, date_approved=None) -> None:
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status=status,
            date_approved=date_approved,
        )
    )


def _day(db, date_range) -> "set[int]":
    scope = build_scope(db, SalesFilter(date_range=date_range))
    rows = scope.base.with_entities(MlOrdersOps.order_id).all()
    return {row.order_id for row in rows}


DAY_A_START = datetime(2026, 9, 25, tzinfo=timezone.utc)
DAY_A_END = DAY_A_START + timedelta(days=1)
DAY_B_START = datetime(2026, 9, 30, tzinfo=timezone.utc)
DAY_B_END = DAY_B_START + timedelta(days=1)


class TestFilterDayIsAccreditationNotCreation:
    def test_sale_created_day_a_accredited_day_b_lands_in_b_not_a(self, db):
        """The production shape (order 2000018641457084): created on the
        25th, its only approved payment accredits on the 30th. Mutate the
        filter back to `date_created` and this goes red."""
        _order(db, 1, date_created=DAY_A_START + timedelta(hours=16, minutes=28))
        _payment(db, payment_id=10, order_id=1, status="rejected", date_approved=None)
        _payment(
            db,
            payment_id=11,
            order_id=1,
            status="approved",
            date_approved=DAY_B_START + timedelta(hours=11, minutes=42),
        )
        db.commit()

        assert _day(db, (DAY_B_START, DAY_B_END)) == {1}
        assert _day(db, (DAY_A_START, DAY_A_END)) == set()


class TestPackDayIsTheLatestMember:
    def test_pack_lands_in_the_later_members_day(self, db):
        """Member 1 accredits day A, member 2 accredits day B -- the pack
        belongs to B (the LAST accreditation), never A. Mutating MAX to MIN
        in `group_accreditation_date_subquery` must fail this test."""
        _order(db, 1, pack_id=777, date_created=DAY_A_START)
        _order(db, 2, pack_id=777, date_created=DAY_A_START)
        _payment(db, payment_id=20, order_id=1, status="approved", date_approved=DAY_A_START + timedelta(hours=10))
        _payment(db, payment_id=21, order_id=2, status="approved", date_approved=DAY_B_START + timedelta(hours=10))
        db.commit()

        assert _day(db, (DAY_B_START, DAY_B_END)) == {1, 2}
        assert _day(db, (DAY_A_START, DAY_A_END)) == set()


class TestSaleWithNoAccreditedPaymentHasNoDay:
    def test_all_rejected_appears_in_no_range(self, db):
        _order(db, 5, date_created=DAY_A_START)
        _payment(db, payment_id=50, order_id=5, status="rejected", date_approved=None)
        db.commit()

        assert _day(db, (DAY_A_START, DAY_A_END)) == set()
        assert _day(db, (DAY_B_START, DAY_B_END)) == set()

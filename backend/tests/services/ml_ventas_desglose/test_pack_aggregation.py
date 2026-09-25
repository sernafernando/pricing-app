"""RED/GREEN tests for `aggregate_pack_metrics` (ventas-ml-rediseno PR18,
design D13, spec `ml-order-breakdown` R36/R37).

`aggregate_pack_metrics` is the SINGLE place summing `total_gauss` and
`costo_mercaderia` across a pack's member orders, all-or-nothing -- the rule
`ml_ventas_ops.py`'s inline `pack_total_gauss` loop and `listar_ventas`'s
`group_total_gauss` block duplicated before this module existed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_ventas_desglose.pack_aggregation import aggregate_pack_metrics, sum_all_or_nothing


def _seed_order(db, order_id: int) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 9, 1, tzinfo=timezone.utc),
            date_created=datetime(2026, 9, 1, tzinfo=timezone.utc),
            seller_id=999,
            total_amount=100,
            paid_amount=100,
            currency_id="ARS",
        )
    )
    db.flush()


def _stored_metrics(db, order_id: int, *, total_gauss=None, costo_mercaderia=None, markup_pct=None) -> None:
    _seed_order(db, order_id)
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=None,
            total_gauss=total_gauss,
            gauss_status="ok" if total_gauss is not None else "unresolved",
            markup_pct=markup_pct,
            costo_mercaderia=costo_mercaderia,
            formula_version=1,
            computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    db.flush()


class TestSumAllOrNothing:
    def test_empty_sequence_is_none(self):
        assert sum_all_or_nothing([]) is None

    def test_any_none_makes_the_whole_sum_none(self):
        assert sum_all_or_nothing([Decimal("10"), None, Decimal("5")]) is None

    def test_all_present_sums(self):
        assert sum_all_or_nothing([Decimal("10"), Decimal("5")]) == Decimal("15")


class TestAggregatePackMetrics:
    def test_three_member_pack_sums_all_or_nothing(self, db):
        """PR18.T3/T5: the sum-of-members invariant -- summing each
        member's own `total_gauss`/`costo_mercaderia` equals the pack
        totals `aggregate_pack_metrics` returns."""
        _stored_metrics(db, 1, total_gauss=Decimal("30.00"), costo_mercaderia=Decimal("10.00"))
        _stored_metrics(db, 2, total_gauss=Decimal("60.00"), costo_mercaderia=Decimal("20.00"))
        _stored_metrics(db, 3, total_gauss=Decimal("90.00"), costo_mercaderia=Decimal("30.00"))

        result = aggregate_pack_metrics(db, [1, 2, 3])

        assert result.total_gauss == Decimal("180.00")
        assert result.costo_mercaderia == Decimal("60.00")
        # markup = total_gauss_pack / costo_mercaderia_pack * 100
        assert result.markup_pct == Decimal("300.00")

    def test_one_member_with_no_stored_row_makes_markup_none_never_partial(self, db):
        """PR18.T11 (R37 scenario 6): a pack member with NO
        `ml_order_metrics` row at all makes the whole pack markup `None`,
        never a partial sum over the members that do have one."""
        _stored_metrics(db, 1, total_gauss=Decimal("30.00"), costo_mercaderia=Decimal("10.00"))
        # order 2 has no stored row at all.

        result = aggregate_pack_metrics(db, [1, 2])

        assert result.total_gauss is None
        assert result.costo_mercaderia is None
        assert result.markup_pct is None

    def test_zero_summed_cost_makes_markup_none_never_a_division_by_zero(self, db):
        """PR18.T11 (R37 scenario 7)."""
        _stored_metrics(db, 1, total_gauss=Decimal("30.00"), costo_mercaderia=Decimal("0.00"))

        result = aggregate_pack_metrics(db, [1])

        assert result.total_gauss == Decimal("30.00")
        assert result.costo_mercaderia == Decimal("0.00")
        assert result.markup_pct is None

    def test_single_member_pack_degenerates_to_that_members_own_values(self, db):
        """PR18.T16/T17 (R40 scenario 10): a one-order "pack" produces the
        same figures as that member's own order-scoped values, with no
        special-casing needed."""
        _stored_metrics(db, 42, total_gauss=Decimal("90.00"), costo_mercaderia=Decimal("10.00"))

        result = aggregate_pack_metrics(db, [42])

        assert result.total_gauss == Decimal("90.00")
        assert result.costo_mercaderia == Decimal("10.00")
        assert result.markup_pct == Decimal("900.00")

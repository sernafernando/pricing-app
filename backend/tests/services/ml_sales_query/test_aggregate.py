"""RED/GREEN tests for `aggregate_order_metrics` (design D12 `aggregate.py`,
spec KPI R8, SM R2/R3, PR11.T4/T5).

Every sum EXCLUDES orders in `recalculating`/`pending`/`failed` state --
never a fabricated zero, always counted separately.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_sales_query.aggregate import aggregate_order_metrics
from app.services.ml_sales_query.filters import SalesFilter, build_scope
from app.services.order_metrics.queue import POISON_THRESHOLD


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _seed_order(
    db,
    order_id: int,
    *,
    total_amount=100,
    currency_id: str = "ARS",
    pack_id: int | None = None,
    date_created=None,
) -> None:
    if date_created is None:
        date_created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=date_created,
            date_created=date_created,
            seller_id=999,
            total_amount=total_amount,
            paid_amount=total_amount,
            currency_id=currency_id,
        )
    )
    db.flush()


def _seed_metrics(
    db,
    order_id: int,
    *,
    neto=100,
    total_gauss=30,
    costo_mercaderia=50,
    markup_pct=60,
    gauss_status: str = "ok",
) -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=neto,
            neto_sin_iva=neto,
            iva_reconcilia=True,
            costo_mercaderia=costo_mercaderia,
            total_gauss=total_gauss,
            markup_pct=markup_pct,
            gauss_status=gauss_status,
            formula_version=1,
            computed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.flush()


def _seed_dirty(db, order_id: int, *, attempts: int = 0) -> None:
    db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=attempts))
    db.flush()


def _aggregate(db, f: SalesFilter | None = None):
    scope = build_scope(db, f or SalesFilter(include_unknown=True, include_in_dispute=True))
    return aggregate_order_metrics(db, scope.listing_query, scope.group_key)


class TestBasicSums:
    def test_single_order_sums(self, db):
        _seed_order(db, 1, total_amount=1000)
        _seed_metrics(db, 1, neto=800, total_gauss=200, costo_mercaderia=500)
        result = _aggregate(db)
        assert result.orders_count == 1
        assert result.groups_count == 1
        assert result.gross_billed_ars == Decimal("1000")
        assert result.neto_sum == Decimal("800")
        assert result.total_gauss_sum == Decimal("200")

    def test_markup_weighted_is_sum_over_sum_never_average_of_percentages(self, db):
        # Order A: tg=100, costo=100 -> 100%. Order B: tg=10, costo=1000 ->
        # 1%. A plain average of the two per-order percentages would read
        # 50.5% -- the weighted rule (design D12) must read
        # SUM(110)/SUM(1100)*100 = 10%.
        _seed_order(db, 1)
        _seed_metrics(db, 1, total_gauss=100, costo_mercaderia=100)
        _seed_order(db, 2)
        _seed_metrics(db, 2, total_gauss=10, costo_mercaderia=1000)
        result = _aggregate(db)
        assert result.markup_weighted_pct == Decimal("10")

    def test_zero_costo_sum_yields_none_markup_not_a_fabricated_zero(self, db):
        _seed_order(db, 1)
        _seed_metrics(db, 1, total_gauss=0, costo_mercaderia=0, markup_pct=None)
        result = _aggregate(db)
        assert result.markup_weighted_pct is None

    def test_currencies_counted_separately_never_mixed_into_ars(self, db):
        _seed_order(db, 1, total_amount=1000, currency_id="ARS")
        _seed_metrics(db, 1)
        _seed_order(db, 2, total_amount=50, currency_id="USD")
        _seed_metrics(db, 2)
        result = _aggregate(db)
        assert result.gross_billed_ars == Decimal("1000")
        assert result.gross_billed_other == {"USD": Decimal("50")}

    def test_gauss_status_counts(self, db):
        _seed_order(db, 1)
        _seed_metrics(db, 1, gauss_status="ok")
        _seed_order(db, 2)
        _seed_metrics(db, 2, gauss_status="provisional")
        _seed_order(db, 3)
        _seed_metrics(db, 3, gauss_status="unresolved", total_gauss=None, markup_pct=None)
        result = _aggregate(db)
        assert result.total_gauss_ok_count == 1
        assert result.total_gauss_provisional_count == 1
        assert result.total_gauss_unresolved_count == 1

    def test_group_of_two_orders_counts_as_one_group_two_orders(self, db):
        _seed_order(db, 1, pack_id=555)
        _seed_metrics(db, 1)
        _seed_order(db, 2, pack_id=555)
        _seed_metrics(db, 2)
        result = _aggregate(db)
        assert result.groups_count == 1
        assert result.orders_count == 2


class TestExclusionFromSums:
    """Design D9/D12, spec KPI R8/R14, SM R2/R3: `recalculating`/`pending`/
    `failed` orders never contribute to any sum -- counted separately."""

    def test_recalculating_order_excluded_from_every_sum(self, db):
        _seed_order(db, 1, total_amount=1000)
        _seed_metrics(db, 1, neto=800, total_gauss=200, costo_mercaderia=500)
        _seed_dirty(db, 1, attempts=0)
        result = _aggregate(db)
        assert result.recalculating_count == 1
        assert result.orders_count == 0
        assert result.gross_billed_ars == Decimal("0")
        assert result.neto_sum == Decimal("0")
        assert result.total_gauss_sum == Decimal("0")

    def test_pending_order_with_no_metrics_row_excluded_and_counted(self, db):
        _seed_order(db, 1, total_amount=1000)
        # No `_seed_metrics` call: no `ml_order_metrics` row at all.
        result = _aggregate(db)
        assert result.pending_count == 1
        assert result.orders_count == 0
        assert result.gross_billed_ars == Decimal("0")

    def test_failed_parked_order_excluded_and_counted_separately_from_recalculating(self, db):
        _seed_order(db, 1, total_amount=1000)
        _seed_metrics(db, 1, neto=800, total_gauss=200, costo_mercaderia=500)
        _seed_dirty(db, 1, attempts=POISON_THRESHOLD)
        result = _aggregate(db)
        assert result.failed_count == 1
        assert result.recalculating_count == 0
        assert result.orders_count == 0

    def test_mixed_batch_reconciles_scanned_count(self, db):
        _seed_order(db, 1, total_amount=100)
        _seed_metrics(db, 1)
        _seed_order(db, 2, total_amount=100)
        _seed_metrics(db, 2)
        _seed_dirty(db, 2, attempts=0)
        _seed_order(db, 3, total_amount=100)
        # pending: no metrics row
        result = _aggregate(db)
        assert result.orders_scanned == 3
        assert result.orders_count == 1
        assert result.recalculating_count == 1
        assert result.pending_count == 1
        assert result.orders_scanned == result.orders_count + result.recalculating_count + result.pending_count


class TestUnknownNeto:
    def test_null_neto_counted_as_unknown_never_summed_as_zero(self, db):
        _seed_order(db, 1)
        _seed_metrics(db, 1, neto=None)
        result = _aggregate(db)
        assert result.neto_unknown_count == 1
        assert result.neto_sum == Decimal("0")


class TestWeightedMarkupOnlyFromOrdersCarryingBothValues:
    """K1 (blocking, money): an order must carry BOTH `total_gauss` and
    `costo_mercaderia` to contribute to EITHER side of the weighted markup
    ratio -- summing the numerator and denominator over two DIFFERENT
    populations produces a plausible-looking percentage that corresponds
    to nothing."""

    def test_order_missing_costo_never_inflates_the_numerator(self, db):
        _seed_order(db, 1)
        _seed_metrics(db, 1, total_gauss=100, costo_mercaderia=None, markup_pct=None)
        _seed_order(db, 2)
        _seed_metrics(db, 2, total_gauss=50, costo_mercaderia=50)
        result = _aggregate(db)
        # Only order 2 carries both values: 50/50*100 = 100%. If order 1's
        # total_gauss leaked into the numerator without its (missing)
        # costo in the denominator, this would read 150/50*100 = 300%.
        assert result.markup_weighted_pct == Decimal("100")
        assert result.markup_skipped_count == 1

    def test_order_missing_total_gauss_never_inflates_the_denominator(self, db):
        _seed_order(db, 1)
        _seed_metrics(db, 1, total_gauss=None, costo_mercaderia=1000, markup_pct=None, gauss_status="unresolved")
        _seed_order(db, 2)
        _seed_metrics(db, 2, total_gauss=50, costo_mercaderia=50)
        result = _aggregate(db)
        # If order 1's costo leaked into the denominator without its
        # (missing) total_gauss in the numerator, this would read
        # 50/1050*100 ~= 4.76%, not the correct 100%.
        assert result.markup_weighted_pct == Decimal("100")
        assert result.markup_skipped_count == 1

    def test_total_gauss_sum_is_unaffected_by_a_missing_costo(self, db):
        """`total_gauss_sum` (spec KPI R8, a separate measure from the
        weighted markup ratio) must still include an order's total_gauss
        even when its costo_mercaderia is missing -- only the markup
        numerator/denominator pairing is exclusion-gated by K1."""
        _seed_order(db, 1)
        _seed_metrics(db, 1, total_gauss=100, costo_mercaderia=None, markup_pct=None)
        result = _aggregate(db)
        assert result.total_gauss_sum == Decimal("100")

    def test_both_missing_is_not_double_counted(self, db):
        _seed_order(db, 1)
        _seed_metrics(db, 1, total_gauss=None, costo_mercaderia=None, markup_pct=None, gauss_status="unresolved")
        result = _aggregate(db)
        assert result.markup_weighted_pct is None
        assert result.markup_skipped_count == 1

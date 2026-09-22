"""`markup_pct` must never crash the producer's write path.

`persistir_total_gauss` (used by the sweep) now goes through
`recompute_order_metrics`, so any value the stored column cannot hold, or
that contradicts the order's own state, aborts the whole batch. The
normalizer turns those into NULL (unknown) instead: never clamped, never
fabricated."""

from __future__ import annotations

from decimal import Decimal

from app.services.order_metrics.compute import MARKUP_PCT_MAX, normalize_markup_pct
from app.services.order_metrics.types import GaussStatus


def test_a_markup_that_overflows_the_column_is_stored_as_unknown() -> None:
    # A 0.01 frozen unit cost on a normal-priced order: total 5000 / 0.01 * 100.
    huge = Decimal("50000000.00")
    assert huge > MARKUP_PCT_MAX
    assert normalize_markup_pct(huge, Decimal("0.01"), GaussStatus.OK, order_id=1) is None


def test_a_negative_markup_beyond_the_column_is_also_unknown() -> None:
    assert normalize_markup_pct(-(MARKUP_PCT_MAX + 1), Decimal("0.01"), GaussStatus.OK, order_id=1) is None


def test_an_unresolved_order_never_carries_a_markup() -> None:
    assert normalize_markup_pct(Decimal("25.00"), Decimal("100.00"), GaussStatus.UNRESOLVED, order_id=1) is None


def test_a_normal_markup_is_kept() -> None:
    assert normalize_markup_pct(Decimal("25.00"), Decimal("100.00"), GaussStatus.OK, order_id=1) == Decimal("25.00")


def test_the_limit_itself_is_kept() -> None:
    assert normalize_markup_pct(MARKUP_PCT_MAX, Decimal("1.00"), GaussStatus.PROVISIONAL, order_id=1) == MARKUP_PCT_MAX


def test_zero_or_missing_cost_is_unknown() -> None:
    assert normalize_markup_pct(Decimal("25.00"), Decimal("0"), GaussStatus.OK, order_id=1) is None
    assert normalize_markup_pct(Decimal("25.00"), None, GaussStatus.OK, order_id=1) is None


def test_an_order_missing_from_the_chain_result_is_skipped(db, monkeypatch) -> None:
    """If `calcular_total_gauss` ever leaves out an existing order, the batch
    must skip it (legacy `persistir_total_gauss` iterated the result dict and
    never indexed a required key), never raise and abort the sweep batch."""
    from datetime import datetime, timezone

    from app.models.ml_orders_ops import MlOrdersOps
    from app.services.order_metrics import compute as compute_module

    for order_id in (71, 72):
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 9, 22, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
    db.commit()

    real = compute_module.calcular_total_gauss

    def _drops_72(db_, order_ids, neto_sin_iva_by_order, *, venta_sin_iva_by_order):
        result = real(db_, order_ids, neto_sin_iva_by_order, venta_sin_iva_by_order=venta_sin_iva_by_order)
        result.pop(72, None)
        return result

    monkeypatch.setattr(compute_module, "calcular_total_gauss", _drops_72)

    metrics = compute_module.compute_order_metrics(db, [71, 72])

    assert 71 in metrics
    assert 72 not in metrics

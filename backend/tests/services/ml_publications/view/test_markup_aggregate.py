"""Variation aggregate (addendum decision 5): range, worst variation, any-negative. Pure."""

from __future__ import annotations

from typing import Optional

from app.services.ml_publications.view.markup import (
    REASON_OK,
    REASON_SIN_COSTO,
    REASON_SIN_VINCULO,
    UnitMarkup,
    aggregate_publication,
)


def unit(value: Optional[float], reason: str = REASON_OK) -> UnitMarkup:
    if value is None:
        return UnitMarkup(None, reason, None, None, None, None, None)
    return UnitMarkup(value, reason, 100.0, 80.0, 150.0, "item_price", 2)


class TestRange:
    def test_all_equal_is_a_single_value(self) -> None:
        agg = aggregate_publication(None, [unit(12.0), unit(12.0)])
        assert (agg.value_min, agg.value_max, agg.worst) == (12.0, 12.0, 12.0)
        assert agg.is_range is False

    def test_range_min_max_and_worst_is_the_min(self) -> None:
        agg = aggregate_publication(None, [unit(18.0), unit(12.0), unit(15.0)])
        assert (agg.value_min, agg.value_max, agg.worst) == (12.0, 18.0, 12.0)
        assert agg.is_range is True
        assert agg.reason == REASON_OK

    def test_any_negative_is_true_when_one_variation_is_negative(self) -> None:
        agg = aggregate_publication(None, [unit(18.0), unit(-1.0)])
        assert agg.any_negative is True
        assert agg.worst == -1.0

    def test_zero_is_not_negative(self) -> None:
        assert aggregate_publication(None, [unit(0.0), unit(5.0)]).any_negative is False

    def test_no_variations_uses_the_item_unit_alone(self) -> None:
        agg = aggregate_publication(unit(9.0), [])
        assert (agg.value_min, agg.value_max, agg.partial, len(agg.variations)) == (9.0, 9.0, 0, 1)


class TestNulls:
    def test_null_variations_are_excluded_and_counted_as_partial(self) -> None:
        agg = aggregate_publication(None, [unit(10.0), unit(None, REASON_SIN_COSTO), unit(20.0)])
        assert (agg.value_min, agg.value_max, agg.worst, agg.partial) == (10.0, 20.0, 10.0, 1)
        assert agg.reason == REASON_OK

    def test_all_null_has_no_value_and_a_reason(self) -> None:
        agg = aggregate_publication(None, [unit(None, REASON_SIN_COSTO), unit(None, REASON_SIN_COSTO)])
        assert (agg.value_min, agg.value_max, agg.worst, agg.any_negative) == (None, None, None, False)
        assert agg.reason == REASON_SIN_COSTO
        assert agg.partial == 0

    def test_a_concrete_reason_wins_over_sin_vinculo(self) -> None:
        agg = aggregate_publication(None, [None, unit(None, REASON_SIN_COSTO)])
        assert agg.reason == REASON_SIN_COSTO


class TestLinks:
    def test_variation_with_own_link_uses_it_else_falls_back_to_the_item_unit(self) -> None:
        agg = aggregate_publication(unit(5.0), [unit(20.0), None])
        assert [v.value for v in agg.variations] == [20.0, 5.0]
        assert (agg.value_min, agg.value_max) == (5.0, 20.0)

    def test_only_item_level_link(self) -> None:
        agg = aggregate_publication(unit(7.0), [None, None])
        assert [v.value for v in agg.variations] == [7.0, 7.0]
        assert agg.is_range is False

    def test_only_variation_links_leave_the_unlinked_one_as_sin_vinculo(self) -> None:
        agg = aggregate_publication(None, [unit(10.0), None])
        assert agg.variations[1].reason == REASON_SIN_VINCULO
        assert agg.variations[1].value is None
        assert (agg.value_min, agg.partial) == (10.0, 1)

    def test_nothing_linked_is_sin_vinculo(self) -> None:
        agg = aggregate_publication(None, [None, None])
        assert (agg.value_min, agg.reason) == (None, REASON_SIN_VINCULO)

    def test_no_units_at_all_is_sin_vinculo(self) -> None:
        agg = aggregate_publication(None, [])
        assert (agg.value_min, agg.reason, len(agg.variations)) == (None, REASON_SIN_VINCULO, 1)

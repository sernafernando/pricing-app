"""Sell-in split: how a purchase discount total is spread across its lines.

Pure arithmetic, no DB. The invariant every formula must keep is that the
assigned amounts add up to EXACTLY `monto_total`, cent for cent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.sell_in.split import Line, SellInSplitError, preview, split, unit_discount

D = Decimal


def _line(item_id: int, cantidad: int, costo: str, manual: str | None = None) -> Line:
    return Line(
        item_id=item_id,
        cantidad=cantidad,
        costo_base_unit=D(costo),
        monto_manual=D(manual) if manual is not None else None,
    )


class TestProporcional:
    def test_weights_by_cost_times_quantity(self) -> None:
        lines = [_line(101, 10, "100"), _line(102, 5, "200"), _line(103, 2, "500")]
        # Line values 1000 / 1000 / 1000 -> equal thirds of 900.
        assert split("proporcional", D("900.00"), lines) == [D("300.00"), D("300.00"), D("300.00")]

    def test_uneven_weights(self) -> None:
        lines = [_line(101, 3, "12.50"), _line(102, 1, "62.50")]
        # Values 37.50 / 62.50 of 100 -> 37.5% / 62.5% of 1000.
        assert split("proporcional", D("1000.00"), lines) == [D("375.00"), D("625.00")]

    def test_remainder_goes_to_the_line_with_the_largest_weight(self) -> None:
        lines = [_line(101, 1, "10"), _line(102, 1, "10"), _line(103, 1, "20")]
        # Weights 10/10/20 of 0.10: 0.025 -> 0.03, 0.03, 0.05 ; sum 0.11 -> -0.01 to line 103.
        result = split("proporcional", D("0.10"), lines)
        assert result == [D("0.03"), D("0.03"), D("0.04")]
        assert sum(result) == D("0.10")

    def test_thirds_sum_exactly_and_the_extra_cent_lands_on_the_heaviest_line(self) -> None:
        lines = [_line(101, 1, "100"), _line(102, 1, "100"), _line(103, 2, "100")]
        # Weights 100/100/200 of 100.00 -> 25/25/50: exact. 100.03 -> 25.0075 -> 25.01,
        # 25.01, 50.015 -> 50.02 ; sum 100.04 -> -0.01 to line 103.
        result = split("proporcional", D("100.03"), lines)
        assert result == [D("25.01"), D("25.01"), D("50.01")]
        assert sum(result) == D("100.03")

    def test_all_costs_zero_is_an_error_not_a_silent_fallback(self) -> None:
        with pytest.raises(SellInSplitError, match="peso"):
            split("proporcional", D("100.00"), [_line(101, 5, "0"), _line(102, 3, "0")])

    def test_a_zero_cost_line_gets_nothing(self) -> None:
        result = split("proporcional", D("50.00"), [_line(101, 5, "0"), _line(102, 1, "10")])
        assert result == [D("0.00"), D("50.00")]


class TestPorUnidad:
    def test_weights_by_quantity_only(self) -> None:
        lines = [_line(101, 1, "1000"), _line(102, 3, "1")]
        assert split("por_unidad", D("400.00"), lines) == [D("100.00"), D("300.00")]

    def test_remainder_on_the_line_with_most_units(self) -> None:
        lines = [_line(101, 1, "5"), _line(102, 1, "5"), _line(103, 1, "5")]
        # 33.333.. each -> 33.33 x3 = 99.99 ; +0.01 to the first of the tied heaviest.
        result = split("por_unidad", D("100.00"), lines)
        assert result == [D("33.34"), D("33.33"), D("33.33")]
        assert sum(result) == D("100.00")


class TestManual:
    def test_uses_the_manual_amounts_as_given(self) -> None:
        lines = [_line(101, 2, "10", manual="70.00"), _line(102, 1, "10", manual="30.00")]
        assert split("manual", D("100.00"), lines) == [D("70.00"), D("30.00")]

    def test_manual_amounts_must_add_up_to_the_total_exactly(self) -> None:
        lines = [_line(101, 2, "10", manual="70.00"), _line(102, 1, "10", manual="29.99")]
        with pytest.raises(SellInSplitError, match="suma"):
            split("manual", D("100.00"), lines)

    def test_every_line_needs_a_manual_amount(self) -> None:
        lines = [_line(101, 2, "10", manual="100.00"), _line(102, 1, "10")]
        with pytest.raises(SellInSplitError, match="manual"):
            split("manual", D("100.00"), lines)

    def test_negative_manual_amount_is_rejected(self) -> None:
        lines = [_line(101, 2, "10", manual="110.00"), _line(102, 1, "10", manual="-10.00")]
        with pytest.raises(SellInSplitError):
            split("manual", D("100.00"), lines)

    def test_sub_cent_manual_amount_is_rejected(self) -> None:
        lines = [_line(101, 2, "10", manual="50.005"), _line(102, 1, "10", manual="49.995")]
        with pytest.raises(SellInSplitError, match="centavos"):
            split("manual", D("100.00"), lines)


class TestErrors:
    def test_empty_lines(self) -> None:
        with pytest.raises(SellInSplitError, match="vac"):
            split("proporcional", D("100.00"), [])

    def test_duplicate_item(self) -> None:
        with pytest.raises(SellInSplitError, match="duplicado"):
            split("proporcional", D("100.00"), [_line(101, 1, "10"), _line(101, 2, "10")])

    def test_unknown_formula(self) -> None:
        with pytest.raises(SellInSplitError, match="rmula"):
            split("ppp", D("100.00"), [_line(101, 1, "10")])

    @pytest.mark.parametrize("total", ["0", "-5.00", "10.001"])
    def test_total_must_be_positive_whole_cents(self, total: str) -> None:
        with pytest.raises(SellInSplitError):
            split("proporcional", D(total), [_line(101, 1, "10")])

    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(SellInSplitError, match="cantidad"):
            split("por_unidad", D("10.00"), [_line(101, 0, "10")])

    def test_negative_cost_is_rejected(self) -> None:
        with pytest.raises(SellInSplitError, match="costo"):
            split("proporcional", D("10.00"), [_line(101, 1, "-1")])


class TestTinyTotals:
    def test_remainder_never_drives_a_line_negative(self) -> None:
        # 8 equal lines of 0.04: each raw share is 0.005 -> HALF_UP 0.01, sum 0.08.
        # Dumping -0.04 on one line would leave it at -0.03; it must spread instead.
        lines = [_line(100 + i, 1, "10") for i in range(8)]
        result = split("por_unidad", D("0.04"), lines)
        assert sum(result) == D("0.04")
        assert all(amount >= 0 for amount in result)


class TestUnitDiscount:
    def test_divides_amount_by_units(self) -> None:
        assert unit_discount(D("300.00"), 4) == D("75.000000")

    def test_rounds_half_up_to_six_decimals(self) -> None:
        assert unit_discount(D("100.00"), 3) == D("33.333333")
        assert unit_discount(D("0.05"), 8) == D("0.006250")

    def test_zero_units_is_an_error(self) -> None:
        with pytest.raises(SellInSplitError, match="cantidad"):
            unit_discount(D("10.00"), 0)


class TestPreview:
    def test_reports_amount_unit_discount_promo_cost_and_percentage(self) -> None:
        lines = [_line(101, 10, "100"), _line(102, 5, "40")]
        rows = preview("proporcional", D("240.00"), lines)
        # Values 1000 / 200 of 1200 -> 200 / 40.
        assert [r.item_id for r in rows] == [101, 102]
        first, second = rows
        assert first.monto_asignado == D("200.00")
        assert first.descuento_unit == D("20.000000")
        assert first.costo_con_sell_in_unit == D("80.000000")
        assert first.porcentaje == D("20.00")
        assert second.monto_asignado == D("40.00")
        assert second.descuento_unit == D("8.000000")
        assert second.costo_con_sell_in_unit == D("32.000000")
        assert second.porcentaje == D("20.00")

    def test_percentage_is_none_when_base_cost_is_zero(self) -> None:
        rows = preview("por_unidad", D("10.00"), [_line(101, 1, "0"), _line(102, 1, "50")])
        assert rows[0].porcentaje is None
        assert rows[0].costo_con_sell_in_unit == D("-5.000000")
        assert rows[1].porcentaje == D("10.00")

    def test_preview_propagates_split_errors(self) -> None:
        with pytest.raises(SellInSplitError):
            preview("proporcional", D("10.00"), [])

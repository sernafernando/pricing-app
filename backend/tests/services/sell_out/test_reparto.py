"""`reparto`: the pure split of a `monto_total` campaign (T26b, S34/S35) and `tope.asignar` on its units."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.services.sell_out import reparto
from app.services.sell_out.reparto import MontoTotal, cuota, repartir, resumen_monto_total, validar
from app.services.sell_out.tope import Campana, Consumo, Linea, asignar


def _consumo(ref: int, item: int, unidades: int, dia: int = 1) -> Consumo:
    return Consumo("ml", ref, item, date(2026, 11, dia), unidades, D("0.00"))


def _filas(consumos) -> list[tuple]:
    return [(c.venta_ref, c.item_id, c.unidades, c.monto) for c in consumos]


class TestCuota:
    def test_a_percentage_share_is_that_percent_of_the_total_in_cents(self) -> None:
        c = MontoTotal(D("1000.00"), {1: (D("33.3333"), None)})
        assert cuota(c, 1) == D("333.33")

    def test_a_fixed_share_is_taken_as_is(self) -> None:
        assert cuota(MontoTotal(D("1000.00"), {1: (None, D("125.50"))}), 1) == D("125.50")

    def test_a_percentage_of_a_negative_total_keeps_its_sign_and_rounds_half_away_from_zero(self) -> None:
        c = MontoTotal(D("-13662075.00"), {1: (D("60"), None), 2: (D("12.5"), None)})
        assert cuota(c, 1) == D("-8197245.00")
        assert cuota(MontoTotal(D("-0.20"), {2: (D("12.5"), None)}), 2) == D("-0.03")

    def test_a_share_loaded_with_vat_is_net_of_its_own_product_vat(self) -> None:
        c = MontoTotal(D("1000.00"), {1: (None, D("121.00")), 2: (D("11.05"), None)}, True, {1: D("21"), 2: D("10.5")})
        assert (cuota(c, 1), cuota(c, 2)) == (D("100.00"), D("100.00"))

    def test_a_share_loaded_with_vat_of_a_product_without_vat_rate_fails(self) -> None:
        with pytest.raises(ValueError):
            cuota(MontoTotal(D("1000.00"), {1: (None, D("121.00"))}, True, {1: None}), 1)


class TestRepartir:
    def test_within_a_product_the_share_goes_by_units_and_its_rows_add_up_exactly(self) -> None:
        c = MontoTotal(D("1000.00"), {1: (None, D("100.00")), 2: (None, D("10.00"))})
        filas = repartir(
            c, [_consumo(1, 1, 1), _consumo(2, 2, 1), _consumo(3, 1, 1), _consumo(4, 2, 2), _consumo(5, 1, 1)]
        )
        assert _filas(filas) == [
            (1, 1, 1, D("33.33")),
            (2, 2, 1, D("3.33")),
            (3, 1, 1, D("33.34")),
            (4, 2, 2, D("6.67")),
            (5, 1, 1, D("33.33")),
        ]

    def test_a_negative_share_spreads_negative(self) -> None:
        c = MontoTotal(D("-300.00"), {1: (None, D("-100.00"))})
        assert [f.monto for f in repartir(c, [_consumo(i, 1, 1) for i in range(3)])] == [
            D("-33.33"),
            D("-33.34"),
            D("-33.33"),
        ]

    def test_a_product_without_a_share_and_a_row_left_with_no_money_write_nothing(self) -> None:
        c = MontoTotal(D("1.00"), {1: (None, D("0.01"))})
        assert _filas(repartir(c, [_consumo(1, 1, 1), _consumo(2, 1, 1), _consumo(3, 9, 5)])) == [(1, 1, 1, D("0.01"))]


class TestResumen:
    def test_shares_without_sales_and_the_unassigned_remainder(self) -> None:
        c = MontoTotal(D("1000.00"), {1: (D("60"), None), 2: (None, D("100.00")), 3: (None, D("50.00"))})
        assert resumen_monto_total(c, con_ventas={1, 2}) == {
            "asignado_sin_ventas": D("50.00"),
            "sin_asignar": D("250.00"),
        }

    def test_a_negative_total_keeps_its_sign(self) -> None:
        c = MontoTotal(D("-1000.00"), {1: (D("50"), None), 2: (None, D("-100.00"))})
        assert resumen_monto_total(c, con_ventas={1}) == {
            "asignado_sin_ventas": D("-100.00"),
            "sin_asignar": D("-400.00"),
        }

    def test_loaded_with_vat_each_share_nets_its_own_product_vat_and_the_remainder_stays_as_loaded(self) -> None:
        # Owner (S37, corrected): VAT comes off with each product's own rate when money is applied to it; the
        # remainder is applied to no product, so it keeps its VAT (no shared nor guessed rate).
        ivas = {1: D("21"), 2: D("10.5")}
        c = MontoTotal(D("1000.00"), {1: (None, D("121.00")), 2: (None, D("110.50"))}, True, ivas)
        assert resumen_monto_total(c, con_ventas=()) == {
            "asignado_sin_ventas": D("200.00"),
            "sin_asignar": D("768.50"),
        }

    def test_nothing_shared_is_all_unassigned(self) -> None:
        assert reparto.resumen_monto_total(MontoTotal(D("5.00"), {}), con_ventas=()) == {
            "asignado_sin_ventas": D("0.00"),
            "sin_asignar": D("5.00"),
        }


class TestValidar:
    def test_shares_adding_up_to_more_than_the_total_are_refused(self) -> None:
        with pytest.raises(ValueError, match="exceed"):
            validar(MontoTotal(D("100.00"), {1: (D("60"), None), 2: (None, D("40.01"))}))

    def test_shares_of_a_negative_total_are_compared_by_size(self) -> None:
        validar(MontoTotal(D("-100.00"), {1: (D("60"), None), 2: (None, D("-40.00"))}))
        with pytest.raises(ValueError, match="exceed"):
            validar(MontoTotal(D("-100.00"), {1: (D("60"), None), 2: (None, D("-40.01"))}))

    def test_a_whole_split_of_an_odd_cent_total_is_not_refused_by_its_rounding(self) -> None:
        validar(MontoTotal(D("100.01"), {1: (D("50"), None), 2: (D("50"), None)}))

    def test_a_fixed_share_with_the_opposite_sign_is_refused(self) -> None:
        with pytest.raises(ValueError, match="sign"):
            validar(MontoTotal(D("-100.00"), {1: (None, D("10.00"))}))

    def test_a_share_without_percent_nor_amount_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="product 1 has no share"):
            validar(MontoTotal(D("100.00"), {1: (None, None)}))

    def test_repartir_refuses_an_invalid_split_before_writing(self) -> None:
        with pytest.raises(ValueError, match="sign"):
            repartir(MontoTotal(D("100.00"), {1: (None, D("-10.00"))}), [_consumo(1, 1, 1)])


class TestTopeUnidades:
    @pytest.mark.parametrize("tope", [{"tope_unidades": 1}, {"tope_monto": D("1")}])
    def test_a_monto_total_campaign_with_a_cap_is_refused(self, tope: dict) -> None:
        with pytest.raises(ValueError, match="no cap"):
            asignar(Campana(tipo="monto_total", moneda="ARS", **tope), [])

    def test_a_monto_total_campaign_takes_the_net_units_with_no_money_and_no_cap(self) -> None:
        campana = Campana(tipo="monto_total", moneda="ARS")
        lineas = [
            Linea("fuera", 1, 7, date(2026, 11, 2), 2),
            Linea("ml", 2, 7, date(2026, 11, 3), 1),
            Linea("fuera", 3, 7, date(2026, 11, 4), -1, objetivo=("fuera", 1)),
        ]
        assert [(c.venta_ref, c.unidades, c.monto) for c in asignar(campana, lineas)] == [
            (1, 1, D("0.00")),
            (2, 1, D("0.00")),
        ]

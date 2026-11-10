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


class TestRepartirPorUnidades:
    """`reparto_criterio = 'unidades'` (tactical monto total, S2 (b)): every unit sold of any product of the campaign
    in its dates gets the same share of the total; no stored share is read."""

    def test_every_unit_of_any_product_gets_the_same_share_and_the_rows_add_up_exactly(self) -> None:
        c = MontoTotal(D("1200.00"), {}, criterio="unidades")
        filas = repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 2), _consumo(3, 3, 4)])
        assert _filas(filas) == [(1, 1, 1, D("171.43")), (2, 2, 2, D("342.86")), (3, 3, 4, D("685.71"))]
        assert sum(f.monto for f in filas) == D("1200.00")

    def test_stored_shares_are_ignored(self) -> None:
        c = MontoTotal(D("100.00"), {1: (None, D("90.00"))}, criterio="unidades")
        assert _filas(repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1)])) == [
            (1, 1, 1, D("50.00")),
            (2, 2, 1, D("50.00")),
        ]

    def test_a_negative_total_spreads_negative_and_exactly(self) -> None:
        c = MontoTotal(D("-100.00"), {}, criterio="unidades")
        filas = repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1), _consumo(3, 2, 1)])
        assert _filas(filas) == [(1, 1, 1, D("-33.33")), (2, 2, 1, D("-33.34")), (3, 2, 1, D("-33.33"))]

    def test_a_return_moves_the_share_to_the_units_kept_through_tope(self) -> None:
        lineas = [
            Linea("ml", 1, 1, date(2026, 11, 1), 2),
            Linea("ml", 2, 2, date(2026, 11, 2), 2),
            Linea("ml", 3, 2, date(2026, 11, 3), -1, objetivo=("ml", 2)),
        ]
        neto = asignar(Campana(tipo="monto_total", moneda="ARS"), lineas)
        filas = repartir(MontoTotal(D("300.00"), {}, criterio="unidades"), neto)
        assert sum(f.monto for f in filas) == D("300.00")
        assert {f.item_id: f.monto for f in filas} == {1: D("200.00"), 2: D("100.00")}

    def test_a_total_loaded_with_vat_is_net_of_each_row_product_vat(self) -> None:
        c = MontoTotal(D("242.00"), {}, True, {1: D("21"), 2: D("21")}, criterio="unidades")
        assert _filas(repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1)])) == [
            (1, 1, 1, D("100.00")),
            (2, 2, 1, D("100.00")),
        ]

    def test_no_sales_writes_no_row_and_the_whole_total_is_sin_asignar(self) -> None:
        c = MontoTotal(D("1200.00"), {}, criterio="unidades")
        assert repartir(c, []) == []
        assert resumen_monto_total(c, []) == {"asignado_sin_ventas": D("0.00"), "sin_asignar": D("1200.00")}

    def test_with_sales_nothing_is_sin_asignar_nor_asignado_sin_ventas(self) -> None:
        c = MontoTotal(D("1200.00"), {}, criterio="unidades")
        assert resumen_monto_total(c, [1]) == {"asignado_sin_ventas": D("0.00"), "sin_asignar": D("0.00")}
        assert reparto.sin_ventas(c, [1]) == {}


class TestIgualesEntreVendidos:
    """Sell out "iguales" (tactical iguales sell out S2/S3), owner: "Si es Sell Out lo que no haya vendido ese producto
    lo consumió otro por ende no, el % no es para ese producto es para el que lo vendió". The total splits in equal
    parts among the products with net sales in `consumos` only; each part spreads over its product's units; no stored
    share is read, so the drain's every rebuild is the recalculation. Sell in keeps `iguales` as fixed shares."""

    def test_sell_out_maps_iguales_to_the_split_among_products_that_sold_and_sell_in_does_not(self) -> None:
        assert reparto.criterio_sell_out("iguales") == reparto.IGUALES_VENDIDOS
        assert [reparto.criterio_sell_out(x) for x in ("unidades", None)] == ["unidades", None]

    def test_only_the_products_that_sold_share_the_total_in_equal_parts_to_the_cent(self) -> None:
        c = MontoTotal(D("100.00"), {}, criterio=reparto.IGUALES_VENDIDOS)
        filas = repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 3), _consumo(3, 3, 1), _consumo(4, 1, 1)])
        assert sum(f.monto for f in filas) == D("100.00")
        por_item = {}
        for f in filas:
            por_item[f.item_id] = por_item.get(f.item_id, D("0")) + f.monto
        assert sorted(por_item.values()) == [D("33.33"), D("33.33"), D("33.34")]
        # Within product 1 its part goes by units over its two rows, cumulative rounding (half of 33.33 or 33.34).
        assert len([f for f in filas if f.item_id == 1]) == 2
        assert {f.monto for f in filas if f.item_id == 1} <= {D("16.66"), D("16.67")}

    def test_a_product_with_no_sale_gets_nothing_and_the_others_carry_it_all(self) -> None:
        c = MontoTotal(D("300.00"), {9: (None, D("100.00"))}, criterio=reparto.IGUALES_VENDIDOS)
        filas = repartir(c, [_consumo(1, 1, 2), _consumo(2, 2, 1)])
        assert _filas(filas) == [(1, 1, 2, D("150.00")), (2, 2, 1, D("150.00"))]
        assert resumen_monto_total(c, [1, 2]) == {"asignado_sin_ventas": D("0.00"), "sin_asignar": D("0.00")}
        assert reparto.sin_ventas(c, [1, 2]) == {}

    def test_a_return_that_leaves_a_product_without_net_units_moves_its_part_to_the_others(self) -> None:
        lineas = [
            Linea("ml", 1, 1, date(2026, 11, 1), 1),
            Linea("ml", 2, 2, date(2026, 11, 2), 1),
            Linea("ml", 3, 2, date(2026, 11, 3), -1, objetivo=("ml", 2)),
        ]
        neto = asignar(Campana(tipo="monto_total", moneda="ARS"), lineas)
        filas = repartir(MontoTotal(D("300.00"), {}, criterio=reparto.IGUALES_VENDIDOS), neto)
        assert {f.item_id: f.monto for f in filas} == {1: D("300.00")}

    def test_a_negative_total_splits_negative_and_exactly(self) -> None:
        c = MontoTotal(D("-100.00"), {}, criterio=reparto.IGUALES_VENDIDOS)
        filas = repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1), _consumo(3, 3, 1)])
        assert sorted(f.monto for f in filas) == [D("-33.34"), D("-33.33"), D("-33.33")]
        assert sum(f.monto for f in filas) == D("-100.00")

    def test_a_total_loaded_with_vat_nets_each_part_of_its_product_vat(self) -> None:
        c = MontoTotal(D("242.00"), {}, True, {1: D("21"), 2: D("10.5")}, criterio=reparto.IGUALES_VENDIDOS)
        assert _filas(repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1)])) == [
            (1, 1, 1, D("100.00")),
            (2, 2, 1, D("109.50")),
        ]

    def test_no_sales_writes_no_row_and_the_whole_total_is_sin_asignar(self) -> None:
        c = MontoTotal(D("1200.00"), {}, criterio=reparto.IGUALES_VENDIDOS)
        assert repartir(c, []) == []
        assert resumen_monto_total(c, []) == {"asignado_sin_ventas": D("0.00"), "sin_asignar": D("1200.00")}

    def test_sell_in_iguales_keeps_its_fixed_shares(self) -> None:
        c = MontoTotal(D("300.00"), {1: (None, D("150.00")), 2: (None, D("150.00"))}, criterio="iguales")
        assert _filas(repartir(c, [_consumo(1, 1, 1)])) == [(1, 1, 1, D("150.00"))]
        assert resumen_monto_total(c, [1]) == {"asignado_sin_ventas": D("150.00"), "sin_asignar": D("0.00")}


class TestCostoEntreVendidos:
    """Sell out "costo" (tactical iguales sell out, orchestrator L2): the same owner rule as "iguales". The stored cost
    shares (fixed when split, proportional to each product's cost) are only weights: the total is split by them among
    the products with net sales in `consumos`; a product with no sale gets nothing. Sell in "costo" is unchanged."""

    def test_sell_out_maps_costo_to_the_split_among_products_that_sold(self) -> None:
        assert reparto.criterio_sell_out("costo") == reparto.COSTO_VENDIDOS

    def test_the_products_that_sold_split_the_whole_total_by_their_cost_shares(self) -> None:
        c = MontoTotal(
            D("1000.00"),
            {1: (None, D("100.00")), 2: (None, D("300.00")), 3: (None, D("600.00"))},
            criterio=reparto.COSTO_VENDIDOS,
        )
        filas = repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 2)])
        assert _filas(filas) == [(1, 1, 1, D("250.00")), (2, 2, 2, D("750.00"))]
        assert resumen_monto_total(c, [1, 2]) == {"asignado_sin_ventas": D("0.00"), "sin_asignar": D("0.00")}
        assert reparto.sin_ventas(c, [1, 2]) == {}

    def test_the_parts_add_up_to_the_total_to_the_cent(self) -> None:
        c = MontoTotal(
            D("100.00"),
            {1: (None, D("33.33")), 2: (None, D("33.33")), 3: (None, D("33.34")), 4: (None, D("1.00"))},
            criterio=reparto.COSTO_VENDIDOS,
        )
        filas = repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1), _consumo(3, 3, 1)])
        assert sum(f.monto for f in filas) == D("100.00")

    def test_a_product_without_a_cost_share_gets_nothing_even_if_it_sold(self) -> None:
        c = MontoTotal(D("300.00"), {1: (None, D("300.00"))}, criterio=reparto.COSTO_VENDIDOS)
        assert _filas(repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1)])) == [(1, 1, 1, D("300.00"))]

    def test_a_negative_total_splits_negative_and_exactly(self) -> None:
        c = MontoTotal(D("-100.00"), {1: (None, D("-25.00")), 2: (None, D("-75.00"))}, criterio=reparto.COSTO_VENDIDOS)
        filas = repartir(c, [_consumo(1, 1, 1), _consumo(2, 2, 1)])
        assert _filas(filas) == [(1, 1, 1, D("-25.00")), (2, 2, 1, D("-75.00"))]

    def test_no_sales_writes_no_row_and_the_whole_total_is_sin_asignar(self) -> None:
        c = MontoTotal(D("1000.00"), {1: (None, D("1000.00"))}, criterio=reparto.COSTO_VENDIDOS)
        assert repartir(c, []) == []
        assert resumen_monto_total(c, []) == {"asignado_sin_ventas": D("0.00"), "sin_asignar": D("1000.00")}

    def test_sell_in_costo_keeps_its_fixed_shares(self) -> None:
        c = MontoTotal(D("1000.00"), {1: (None, D("250.00")), 2: (None, D("750.00"))}, criterio="costo")
        assert _filas(repartir(c, [_consumo(1, 1, 1)])) == [(1, 1, 1, D("250.00"))]
        assert resumen_monto_total(c, [1]) == {"asignado_sin_ventas": D("750.00"), "sin_asignar": D("0.00")}

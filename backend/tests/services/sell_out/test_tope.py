"""`tope.asignar`: the pure sell-out cap allocation of ONE campaign (T7 S1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.services.sell_out.tope import Campana, Linea, asignar


def _campana(**overrides) -> Campana:
    values = {"tipo": "por_unidad", "moneda": "USD", "monto_unit": D("10")}
    values.update(overrides)
    return Campana(**values)


def _linea(ref: int, unidades: int, dia: int = 1, item: int = 1, canal: str = "ml", **kw) -> Linea:
    return Linea(canal=canal, venta_ref=ref, item_id=item, fecha=date(2026, 11, dia), unidades=unidades, **kw)


def _filas(consumos) -> list[tuple]:
    return [(c.canal, c.venta_ref, c.unidades, c.monto) for c in consumos]


# ── No cap ──────────────────────────────────────────────────────────


def test_without_a_cap_every_sale_takes_all_its_units() -> None:
    consumos = asignar(_campana(), [_linea(1, 3), _linea(2, 400, dia=2)])
    assert _filas(consumos) == [("ml", 1, 3, D("30.00")), ("ml", 2, 400, D("4000.00"))]


def test_a_row_carries_the_sale_product_and_date() -> None:
    (consumo,) = asignar(_campana(), [_linea(7, 1, dia=9, item=4242, canal="fuera")])
    assert (consumo.item_id, consumo.fecha_venta, consumo.canal, consumo.venta_ref) == (
        4242,
        date(2026, 11, 9),
        "fuera",
        7,
    )


# ── Unit cap and ordering ───────────────────────────────────────────


def test_the_unit_cap_goes_in_strict_sale_date_order_whatever_the_input_order() -> None:
    # Ref 1 arrived first but is dated later: the earlier sale takes the cap first.
    lineas = [_linea(1, 2, dia=5), _linea(2, 2, dia=2)]
    assert _filas(asignar(_campana(tope_unidades=3), lineas)) == [("ml", 2, 2, D("20.00")), ("ml", 1, 1, D("10.00"))]


def test_same_day_sales_tie_by_channel_then_reference() -> None:
    lineas = [_linea(5, 1, canal="ml"), _linea(9, 1, canal="fuera"), _linea(3, 1, canal="fuera")]
    assert _filas(asignar(_campana(tope_unidades=2), lineas)) == [
        ("fuera", 3, 1, D("10.00")),
        ("fuera", 9, 1, D("10.00")),
    ]


def test_references_order_as_numbers() -> None:
    lineas = [_linea(10, 1), _linea(9, 1)]
    assert _filas(asignar(_campana(tope_unidades=1), lineas)) == [("ml", 9, 1, D("10.00"))]


def test_a_line_is_split_at_the_cap_and_later_sales_get_nothing() -> None:
    lineas = [_linea(1, 8), _linea(2, 4, dia=2)]
    assert _filas(asignar(_campana(tope_unidades=5), lineas)) == [("ml", 1, 5, D("50.00"))]


# ── Returns ─────────────────────────────────────────────────────────


def test_a_return_frees_units_for_the_next_sale_in_order() -> None:
    lineas = [_linea(1, 2, dia=1), _linea(2, -1, dia=2, objetivo=("ml", 1)), _linea(3, 2, dia=3)]
    assert _filas(asignar(_campana(tope_unidades=2), lineas)) == [("ml", 1, 1, D("10.00")), ("ml", 3, 1, D("10.00"))]


def test_a_same_day_return_comes_after_the_sales_of_its_day() -> None:
    # The return's reference sorts before its sale's, yet it must find the sale done.
    lineas = [_linea(5, 1), _linea(1, -1, objetivo=("ml", 5)), _linea(9, 1, dia=2)]
    assert _filas(asignar(_campana(tope_unidades=1), lineas)) == [("ml", 9, 1, D("10.00"))]


def test_a_return_takes_its_target_first_then_the_latest_holder_of_the_same_product() -> None:
    lineas = [
        _linea(1, 2, dia=1, item=1),
        _linea(2, 2, dia=2, item=1),
        _linea(3, 2, dia=3, item=2),  # latest holder, but another product
        _linea(4, -3, dia=4, item=1, objetivo=("ml", 1)),
    ]
    assert _filas(asignar(_campana(), lineas)) == [("ml", 2, 1, D("10.00")), ("ml", 3, 2, D("20.00"))]


def test_a_return_without_target_frees_the_latest_holder() -> None:
    lineas = [_linea(1, 2, dia=1), _linea(2, 2, dia=2), _linea(3, -1, dia=3)]
    assert _filas(asignar(_campana(), lineas)) == [("ml", 1, 2, D("20.00")), ("ml", 2, 1, D("10.00"))]


def test_a_return_of_a_product_nobody_holds_frees_nothing() -> None:
    lineas = [_linea(1, 2, item=1), _linea(2, -2, dia=2, item=2), _linea(3, 1, dia=3, item=2)]
    assert _filas(asignar(_campana(tope_unidades=2), lineas)) == [("ml", 1, 2, D("20.00"))]


def test_a_lone_return_is_harmless() -> None:
    assert asignar(_campana(tope_unidades=2), [_linea(1, -3)]) == []


# ── Money cap ───────────────────────────────────────────────────────


def test_the_money_cap_caps_the_last_line_at_the_money_left() -> None:
    lineas = [_linea(1, 2), _linea(2, 2, dia=2), _linea(3, 1, dia=3)]
    assert _filas(asignar(_campana(tope_monto=D("25")), lineas)) == [("ml", 1, 2, D("20.00")), ("ml", 2, 1, D("5.00"))]


def test_the_cap_that_binds_first_wins() -> None:
    campana = _campana(tope_unidades=3, tope_monto=D("100"))
    assert _filas(asignar(campana, [_linea(1, 5)])) == [("ml", 1, 3, D("30.00"))]
    campana = _campana(tope_unidades=30, tope_monto=D("35"))
    assert _filas(asignar(campana, [_linea(1, 5)])) == [("ml", 1, 4, D("35.00"))]


def test_a_return_frees_money_for_the_next_sale() -> None:
    lineas = [_linea(1, 2, dia=1), _linea(2, -1, dia=2, objetivo=("ml", 1)), _linea(3, 2, dia=3)]
    campana = _campana(tope_monto=D("20"))
    assert _filas(asignar(campana, lineas)) == [("ml", 1, 1, D("10.00")), ("ml", 3, 1, D("10.00"))]


def test_a_return_on_a_money_capped_line_keeps_only_what_its_units_are_worth() -> None:
    # Ref 2 holds 2 units worth 15 (capped). Returning one leaves 1 unit worth min(15, 10) = 10.
    lineas = [_linea(1, 1), _linea(2, 3, dia=2), _linea(3, -1, dia=3, objetivo=("ml", 2))]
    campana = _campana(tope_monto=D("25"))
    assert _filas(asignar(campana, lineas)) == [("ml", 1, 1, D("10.00")), ("ml", 2, 1, D("10.00"))]


# ── VAT and the percentage base ─────────────────────────────────────


def test_an_amount_with_vat_is_divided_by_each_products_own_rate() -> None:
    campana = _campana(monto_unit=D("121"), monto_incluye_iva=True)
    lineas = [_linea(1, 2, item=1, iva_pct=D("21")), _linea(2, 3, item=2, iva_pct=D("10.5"))]
    # 121 / 1.21 = 100; 3 * 121 / 1.105 = 328.5067...
    assert _filas(asignar(campana, lineas)) == [("ml", 1, 2, D("200.00")), ("ml", 2, 3, D("328.51"))]


def test_an_amount_without_vat_applies_as_is() -> None:
    campana = _campana(monto_unit=D("121"))
    assert _filas(asignar(campana, [_linea(1, 2, iva_pct=D("21"))])) == [("ml", 1, 2, D("242.00"))]


def test_vat_division_counts_against_the_money_cap() -> None:
    campana = _campana(monto_unit=D("121"), monto_incluye_iva=True, tope_monto=D("250"))
    assert _filas(asignar(campana, [_linea(1, 5, iva_pct=D("21"))])) == [("ml", 1, 3, D("250.00"))]


def test_a_percentage_applies_to_the_unit_base() -> None:
    campana = _campana(tipo="porcentaje", monto_unit=None, porcentaje=D("2.5"))
    assert _filas(asignar(campana, [_linea(1, 3, base_unit=D("1000"))])) == [("ml", 1, 3, D("75.00"))]


def test_a_percentage_base_is_already_without_vat() -> None:
    campana = _campana(tipo="porcentaje", monto_unit=None, porcentaje=D("10"), monto_incluye_iva=True)
    assert _filas(asignar(campana, [_linea(1, 1, base_unit=D("200"), iva_pct=D("21"))])) == [("ml", 1, 1, D("20.00"))]


def test_a_percentage_line_without_base_is_refused() -> None:
    campana = _campana(tipo="porcentaje", monto_unit=None, porcentaje=D("10"))
    with pytest.raises(ValueError):
        asignar(campana, [_linea(1, 1)])


# ── Rounding ────────────────────────────────────────────────────────


def test_each_row_rounds_half_up_to_cents_once() -> None:
    # 5% of 2.50 = 0.125 per unit: one unit is 0.13 (half up), three are 0.375 -> 0.38.
    campana = _campana(tipo="porcentaje", monto_unit=None, porcentaje=D("5"))
    lineas = [_linea(1, 1, base_unit=D("2.50")), _linea(2, 3, dia=2, base_unit=D("2.50"))]
    assert _filas(asignar(campana, lineas)) == [("ml", 1, 1, D("0.13")), ("ml", 2, 3, D("0.38"))]


# ── Zero, occupied and invalid lines ────────────────────────────────


def test_zero_and_fully_occupied_lines_take_nothing() -> None:
    lineas = [_linea(1, 0), _linea(2, 3, ocupadas=3), _linea(3, 2, dia=2)]
    assert _filas(asignar(_campana(tope_unidades=2), lineas)) == [("ml", 3, 2, D("20.00"))]


def test_units_taken_by_an_exclusive_campaign_are_not_available() -> None:
    assert _filas(asignar(_campana(), [_linea(1, 5, ocupadas=2)])) == [("ml", 1, 3, D("30.00"))]


def test_a_return_frees_only_the_units_this_campaign_holds() -> None:
    # 2 of the 3 returned units went back to the exclusive campaign.
    lineas = [_linea(1, 3), _linea(2, 3, dia=2), _linea(3, -3, dia=3, ocupadas=2, objetivo=("ml", 1))]
    assert _filas(asignar(_campana(), lineas)) == [("ml", 1, 2, D("20.00")), ("ml", 2, 3, D("30.00"))]


@pytest.mark.parametrize(
    "lineas",
    [
        [_linea(1, 2), _linea(1, 3, dia=2)],  # the same sale twice
        [_linea(1, 2, ocupadas=3)],
        [_linea(1, 2, ocupadas=-1)],
        [_linea(1, -2, ocupadas=3)],
        [_linea(1, 2, iva_pct=D("-1"))],
    ],
)
def test_invalid_lines_are_refused(lineas) -> None:
    with pytest.raises(ValueError):
        asignar(_campana(), lineas)


@pytest.mark.parametrize(
    "overrides",
    [
        {"monto_unit": None},
        {"tipo": "porcentaje", "monto_unit": None},
        {"tipo": "bono"},
        {"tope_unidades": 0},
        {"tope_monto": D("0")},
    ],
)
def test_invalid_campaigns_are_refused(overrides) -> None:
    with pytest.raises(ValueError):
        asignar(_campana(**overrides), [_linea(1, 1)])

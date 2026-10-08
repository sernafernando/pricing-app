"""One-unit publication markup: the Productos maths applied to a publication.

No database: the `PricingContext` is built by hand. The commission numbers of the
16 captured cases are the ground truth ML returned from `listing_prices`
(Engram #2248, S26.1); every other expectation is the value the SAME pure
`pricing_calculator` functions give for the same inputs (S23.1).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.ml_publications.view import markup as markup_module
from app.services.ml_publications.view.markup import UnitInputs, UnitMarkup, unit_markup
from app.services.pricing_calculator import (
    MONTOT1,
    MONTOT2,
    MONTOT3,
    TIER1,
    TIER2,
    TIER3,
    VARIOS_DEFAULT,
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
)
from app.services.pricing_context import PricingContext, resolve_envio
from tests.services.ml_publications.conftest import load_fixture

CONSTANTES = {
    "monto_tier1": MONTOT1,
    "monto_tier2": MONTOT2,
    "monto_tier3": MONTOT3,
    "tier1": TIER1,
    "tier2": TIER2,
    "tier3": TIER3,
    "varios": VARIOS_DEFAULT,
}

# Base commission per grupo and installments add-on, as ML reported them in the
# capture (`meli_percentage_fee`, `financing_add_on_fee`).
BASE_BY_GRUPO = {1: 15.5, 4: 12.5, 6: 14.0, 10: 14.5}
ADICIONAL_BY_CUOTAS = {3: 8.9, 6: 13.4, 9: 17.8, 12: 21.6}

CASES = load_fixture("listing_prices_cases.json")["cases"]
# subcategory -> grupo exactly as the capture recorded them.
SUBCAT_TO_GRUPO = {c["ours"]["subcategoria_id"]: c["ours"]["grupo_id"] for c in CASES}


def make_ctx(**overrides) -> PricingContext:
    values = dict(
        hoy=date(2026, 10, 8),
        tipo_cambio_usd=1000.0,
        constantes=CONSTANTES,
        subcat_to_grupo=SUBCAT_TO_GRUPO,
        active_version_id=7,
        comision_base=BASE_BY_GRUPO,
        comision_adicional=ADICIONAL_BY_CUOTAS,
        envio_promedio_by_grupo={1: 2000.0, 4: 0.0, 6: 0.0, 10: 0.0},
    )
    values.update(overrides)
    return PricingContext(**values)


def make_inputs(**overrides) -> UnitInputs:
    values = dict(
        item_id="MLA1854372829",
        listing_type_id="gold_pro",
        tags=("9x_campaign",),
        sale_terms_campaign=None,
        sale_price=100000.0,
        item_price=90000.0,
        fallback_prices={},
        producto_item_id=555,
        costo=50000.0,
        moneda_costo="ARS",
        iva=21.0,
        envio=0.0,
        subcategoria_id=3845,
    )
    values.update(overrides)
    return UnitInputs(**values)


def _expected(ctx, *, price, pricelist, grupo, costo_ars, iva=21.0, envio_real=None, producto_envio=0.0):
    base = ctx.comision(pricelist, grupo)
    comis = calcular_comision_ml_total(price, base, iva, constantes=ctx.constantes)
    envio = resolve_envio(ctx, envio_real or {}, 555, producto_envio, grupo, price)
    limpio = calcular_limpio(price, iva, envio, comis["comision_total"], constantes=ctx.constantes)
    return limpio, calcular_markup(limpio, costo_ars) * 100


# --- the 16 captured cases (S26.1) -------------------------------------------


def _captured_percentage_fee(case: dict) -> float:
    # With a campaign ML only quotes the right add-on when `tags=<campaign>` is passed.
    call = case["ml"].get("with_tag") or case["ml"]["by_type"]
    return call["body"]["sale_fee_details"]["percentage_fee"]


def _sale_term_campaign(case: dict):
    for term in case["sale_terms"]:
        if term["id"] == "INSTALLMENTS_CAMPAIGN":
            return term["value_name"]
    return None


def test_the_base_and_addon_assumed_here_are_what_ml_quoted():
    for case in CASES:
        details = (case["ml"].get("with_tag") or case["ml"]["by_type"])["body"]["sale_fee_details"]
        assert BASE_BY_GRUPO[case["ours"]["grupo_id"]] == details["meli_percentage_fee"], case["item_id"]


@pytest.mark.parametrize("case", CASES, ids=[c["item_id"] for c in CASES])
def test_commission_of_our_list_equals_the_percentage_fee_ml_quotes(case):
    ctx = make_ctx()
    ours = case["ours"]
    assert ctx.comision(ours["pricelist_id"], ours["grupo_id"]) == pytest.approx(_captured_percentage_fee(case))


@pytest.mark.parametrize("case", CASES, ids=[c["item_id"] for c in CASES])
def test_unit_markup_prices_each_captured_item_on_the_list_ml_charges(case):
    ctx = make_ctx()
    ours = case["ours"]
    inputs = make_inputs(
        item_id=case["item_id"],
        listing_type_id=case["listing_type_id"],
        tags=tuple(case["tags"]),
        sale_terms_campaign=_sale_term_campaign(case),
        sale_price=case["price"],
        subcategoria_id=ours["subcategoria_id"],
    )
    got = unit_markup(ctx, inputs, {})
    assert got.pricelist_id == ours["pricelist_id"]
    assert got.reason == "ok" and got.source == "sale_price" and got.price == case["price"]
    limpio, value = _expected(
        ctx, price=case["price"], pricelist=ours["pricelist_id"], grupo=ours["grupo_id"], costo_ars=50000.0
    )
    assert got.limpio == limpio and got.value == value


# --- price precedence ---------------------------------------------------------


def test_sale_price_wins_over_item_price_and_fallback():
    got = unit_markup(make_ctx(), make_inputs(fallback_prices={"precio_9_cuotas": 80000.0}), {})
    assert (got.price, got.source) == (100000.0, "sale_price")


def test_item_price_is_used_when_there_is_no_sale_price():
    for no_sale_price in (None, 0, 0.0):
        got = unit_markup(make_ctx(), make_inputs(sale_price=no_sale_price), {})
        assert (got.price, got.source) == (90000.0, "item_price")


def test_productos_price_of_the_resolved_list_is_the_last_resort():
    inputs = make_inputs(
        sale_price=None,
        item_price=None,
        fallback_prices={"precio_9_cuotas": 80000.0, "precio_6_cuotas": 70000.0},
    )
    got = unit_markup(make_ctx(), inputs, {})
    assert (got.price, got.source, got.pricelist_id) == (80000.0, "productos_fallback", 13)


def test_no_price_anywhere_is_sin_precio():
    got = unit_markup(
        make_ctx(), make_inputs(sale_price=None, item_price=0, fallback_prices={"precio_9_cuotas": None}), {}
    )
    assert got.value is None and got.reason == "sin_precio" and got.price is None and got.source is None


# --- reasons: never a made-up number ------------------------------------------


def test_no_link_is_sin_vinculo():
    got = unit_markup(make_ctx(), make_inputs(producto_item_id=None, costo=None), {})
    assert got == UnitMarkup(None, "sin_vinculo", None, None, None, None, None)


@pytest.mark.parametrize("costo", [None, 0, 0.0, -10.0])
def test_no_cost_gives_none_never_zero(costo):
    # `calcular_markup` itself returns 0 when cost is 0; the publication must say "unknown".
    got = unit_markup(make_ctx(), make_inputs(costo=costo), {})
    assert got.value is None and got.reason == "sin_costo"


def test_pcj_co_funded_is_cofinanciada():
    got = unit_markup(make_ctx(), make_inputs(listing_type_id="gold_special", tags=("pcj-co-funded",)), {})
    assert got.value is None and got.reason == "cofinanciada" and got.pricelist_id is None


def test_listing_type_without_a_list_is_sin_lista():
    got = unit_markup(make_ctx(), make_inputs(listing_type_id="free", tags=()), {})
    assert got.value is None and got.reason == "sin_lista"


def test_grupo_without_commission_is_sin_comision():
    got = unit_markup(make_ctx(comision_base={}), make_inputs(), {})
    assert got.value is None and got.reason == "sin_comision" and got.pricelist_id == 13


def test_no_active_commission_version_is_sin_comision():
    got = unit_markup(make_ctx(active_version_id=None), make_inputs(), {})
    assert got.value is None and got.reason == "sin_comision"


# --- parity with Productos (S23.1) --------------------------------------------


def test_markup_is_what_the_productos_calls_give():
    ctx = make_ctx()
    got = unit_markup(ctx, make_inputs(), {})
    limpio, value = _expected(ctx, price=100000.0, pricelist=13, grupo=1, costo_ars=50000.0)
    assert got == UnitMarkup(value, "ok", limpio, 50000.0, 100000.0, "sale_price", 13)
    assert got.value == pytest.approx((limpio / 50000.0 - 1) * 100)


def test_usd_cost_is_converted_with_the_context_rate():
    ctx = make_ctx(tipo_cambio_usd=1200.0)
    got = unit_markup(ctx, make_inputs(costo=40.0, moneda_costo="USD"), {})
    assert got.costo_ars == 48000.0
    limpio, value = _expected(ctx, price=100000.0, pricelist=13, grupo=1, costo_ars=48000.0)
    assert got.value == value and got.limpio == limpio


def test_real_shipping_cost_of_the_linked_product_is_used():
    ctx = make_ctx()
    got = unit_markup(ctx, make_inputs(sale_price=120000.0), {555: 7000.0})
    limpio, _ = _expected(ctx, price=120000.0, pricelist=13, grupo=1, costo_ars=50000.0, envio_real={555: 7000.0})
    assert got.limpio == limpio
    assert got.limpio != unit_markup(ctx, make_inputs(sale_price=120000.0), {}).limpio


def test_grupo_average_shipping_applies_above_the_free_shipping_threshold():
    ctx = make_ctx()
    above = unit_markup(ctx, make_inputs(sale_price=120000.0, envio=0.0), {})
    limpio, _ = _expected(ctx, price=120000.0, pricelist=13, grupo=1, costo_ars=50000.0)
    assert above.limpio == limpio
    # grupo 1 averages 2000: it must differ from a grupo with no average.
    no_avg = unit_markup(make_ctx(envio_promedio_by_grupo={1: 0.0}), make_inputs(sale_price=120000.0), {})
    assert above.limpio < no_avg.limpio


def test_unmapped_subcategory_uses_the_default_grupo():
    ctx = make_ctx(comision_base={1: 15.5})
    got = unit_markup(ctx, make_inputs(subcategoria_id=999999), {})
    assert got.reason == "ok"


# --- shipping goes through resolve_envio and never a null db ------------------


def test_shipping_is_resolved_by_resolve_envio_and_limpio_never_gets_a_db(monkeypatch):
    ctx = make_ctx()
    envio_map = {555: 1234.0}
    envio_calls, limpio_calls = [], []

    def spy_envio(*args, **kwargs):
        envio_calls.append((args, kwargs))
        return resolve_envio(*args, **kwargs)

    def spy_limpio(*args, **kwargs):
        limpio_calls.append((args, kwargs))
        return calcular_limpio(*args, **kwargs)

    monkeypatch.setattr(markup_module, "resolve_envio", spy_envio)
    monkeypatch.setattr(markup_module, "calcular_limpio", spy_limpio)

    unit_markup(ctx, make_inputs(envio=300.0), envio_map)

    assert len(envio_calls) == 1
    assert envio_calls[0][0] == (ctx, envio_map, 555, 300.0, 1, 100000.0)
    assert len(limpio_calls) == 1
    assert "db" not in limpio_calls[0][1] and "grupo_id" not in limpio_calls[0][1]
    assert limpio_calls[0][1]["constantes"] is ctx.constantes

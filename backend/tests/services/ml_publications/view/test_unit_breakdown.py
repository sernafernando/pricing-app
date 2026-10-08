"""P8a: the markup breakdown of one unit (the figures the detail panel shows), and the shipping source behind it.

No database. The breakdown is not a second formula: it is the intermediate figures of `unit_markup` itself, so
every number is pinned against the very pure functions the markup calls, and its `markup` against `unit_markup`.
"""

from __future__ import annotations

import pytest

from app.services.ml_publications.view.markup import UnitBreakdown, unit_breakdown, unit_markup
from app.services.pricing_calculator import calcular_comision_ml_total, calcular_limpio
from app.services.pricing_context import (
    ENVIO_ERP,
    ENVIO_GRUPO_PROMEDIO,
    ENVIO_REAL,
    resolve_envio,
    resolve_envio_source,
)
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs


class TestShippingSource:
    def test_the_real_cost_wins(self) -> None:
        ctx = make_ctx()
        assert resolve_envio_source(ctx, {555: 1234.0}, 555, 99.0, 1, 100000.0) == (1234.0, ENVIO_REAL)

    def test_the_erp_cost_when_there_is_no_real_one(self) -> None:
        assert resolve_envio_source(make_ctx(), {}, 555, 321.0, 1, 100000.0) == (321.0, ENVIO_ERP)

    def test_the_group_average_for_a_pricey_publication_without_any_cost(self) -> None:
        # grupo 1 averages 2000 in the hand-built context; the price is over the third tier
        assert resolve_envio_source(make_ctx(), {}, 555, 0.0, 1, 100000.0) == (2000.0, ENVIO_GRUPO_PROMEDIO)

    def test_no_cost_anywhere_is_an_erp_zero_not_an_average_that_did_not_apply(self) -> None:
        assert resolve_envio_source(make_ctx(), {}, 555, 0.0, 1, 100.0) == (0.0, ENVIO_ERP)
        assert resolve_envio_source(make_ctx(), {}, 555, 0.0, 4, 100000.0) == (0.0, ENVIO_ERP)  # grupo 4 averages 0

    @pytest.mark.parametrize("real", [{}, {555: 777.0}])
    @pytest.mark.parametrize("producto_envio", [0.0, 450.0])
    @pytest.mark.parametrize("price", [100.0, 100000.0])
    def test_resolve_envio_is_the_same_value_as_before(self, real, producto_envio, price) -> None:
        ctx = make_ctx()
        assert (
            resolve_envio(ctx, real, 555, producto_envio, 1, price)
            == resolve_envio_source(ctx, real, 555, producto_envio, 1, price)[0]
        )


class TestBreakdown:
    def test_every_figure_is_the_one_unit_markup_computed(self) -> None:
        ctx, inputs = make_ctx(), make_inputs()
        unit = unit_markup(ctx, inputs, {})
        breakdown = unit_breakdown(ctx, inputs, {})
        assert isinstance(breakdown, UnitBreakdown)
        assert breakdown.markup == unit.value
        assert breakdown.limpio == unit.limpio and breakdown.costo_ars == unit.costo_ars
        assert breakdown.price == unit.price == 100000.0
        assert breakdown.price_source == unit.source == "sale_price"
        assert breakdown.pricelist_id == unit.pricelist_id == 13

    def test_the_commission_and_the_net_are_the_pure_functions_of_the_same_inputs(self) -> None:
        ctx, inputs = make_ctx(), make_inputs(iva=10.5)
        breakdown = unit_breakdown(ctx, inputs, {})
        base = ctx.comision(13, ctx.grupo_of(3845))
        comision = calcular_comision_ml_total(100000.0, base, 10.5, constantes=ctx.constantes)
        envio = resolve_envio(ctx, {}, 555, 0.0, ctx.grupo_of(3845), 100000.0)
        assert breakdown.comision_pct == base
        assert breakdown.comision_total == comision["comision_total"]
        assert breakdown.costo_envio == envio
        assert breakdown.limpio == calcular_limpio(
            100000.0, 10.5, envio, comision["comision_total"], constantes=ctx.constantes
        )

    def test_the_installments_follow_the_list(self) -> None:
        assert unit_breakdown(make_ctx(), make_inputs(), {}).installments == 9  # list 13 is the 9x campaign
        classic = make_inputs(listing_type_id="gold_special", tags=())
        assert unit_breakdown(make_ctx(), classic, {}).installments is None  # the classic list has no installments

    def test_the_shipping_source_is_reported(self) -> None:
        ctx = make_ctx()
        assert unit_breakdown(ctx, make_inputs(), {555: 900.0}).envio_source == ENVIO_REAL
        assert unit_breakdown(ctx, make_inputs(envio=300.0), {}).envio_source == ENVIO_ERP

    def test_a_usd_cost_is_shown_converted(self) -> None:
        ctx = make_ctx()
        breakdown = unit_breakdown(ctx, make_inputs(costo=50.0, moneda_costo="USD"), {})
        assert breakdown.costo_ars == 50.0 * 1000.0

    @pytest.mark.parametrize(
        "overrides",
        [
            {"producto_item_id": None},
            {"costo": None},
            {"costo": 0.0},
            {"listing_type_id": "free"},
            {"sale_price": None, "item_price": None},
        ],
    )
    def test_what_unit_markup_cannot_price_has_no_breakdown(self, overrides) -> None:
        inputs = make_inputs(**overrides)
        assert unit_markup(make_ctx(), inputs, {}).value is None
        assert unit_breakdown(make_ctx(), inputs, {}) is None

    def test_without_commission_there_is_no_breakdown(self) -> None:
        ctx = make_ctx(active_version_id=None)
        assert unit_markup(ctx, make_inputs(), {}).reason == "sin_comision"
        assert unit_breakdown(ctx, make_inputs(), {}) is None

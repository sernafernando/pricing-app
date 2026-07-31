"""Unit tests for `app.services.pxq_markup` (quantity-aware PxQ markup).

Spec coverage (ml-wholesale-pxq):
  - Quantity-aware markup: the low-price fixed charge (tier bracket in
    `calcular_comision_ml_total`) is evaluated on the ORDER TOTAL
    (unit price * quantity), and `calcular_limpio` subtracts the
    WHOLE-SHIPMENT shipping cost exactly once, never a single unit's cost
    multiplied by N and never a single unit's cost for an N-unit order.
  - Fail-closed shipping resolution is STRUCTURAL: `resolve_tier_shipping`
    returns `None` when a tier isn't ready to price, and the wrapper's
    shipping parameter has no default whatsoever.
  - No base-price side effects: this module must never import
    `ProductoPricing` (covered by the AST scan test in a separate file).
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.pricing_calculator import (
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
)
from app.services.pxq_markup import (
    resolve_order_cost,
    ShipmentShippingCost,
    calcular_markup_pxq,
    resolve_tier_shipping,
)

COMISION_BASE_PCT = 20.0
IVA = 21.0
COSTO = 1000.0


def _make_tier(cantidad_minima: int, costo_envio_total):
    return SimpleNamespace(cantidad_minima=cantidad_minima, costo_envio_total=costo_envio_total)


def _expected(precio_unitario: float, cantidad_minima: int, envio_total: float) -> dict:
    """Canonical chain, called directly with the ORDER TOTAL and the
    whole-shipment shipping cost — this is the ground truth the wrapper
    must reproduce exactly."""
    precio_total = precio_unitario * cantidad_minima
    comisiones = calcular_comision_ml_total(precio_total, COMISION_BASE_PCT, IVA)
    limpio = calcular_limpio(precio_total, IVA, envio_total, comisiones["comision_total"])
    markup = calcular_markup(limpio, COSTO * cantidad_minima)
    return {
        "precio_total": precio_total,
        "comision_total": comisiones["comision_total"],
        "limpio": limpio,
        "markup": markup,
    }


class TestDecimalInputsFromRealRows:
    """`MlPxqTier.precio_unitario` / `costo_envio_total` are `Numeric(14, 2)`,
    so a real row yields `Decimal`, not `float`. The pricing chain multiplies
    against float constants, so an un-normalized Decimal raises
    `TypeError: unsupported operand type(s) for *: 'decimal.Decimal' and 'float'`.

    Every other test in this file passes float literals, which is exactly why
    this gap survived: the first caller handing over a real row would have been
    the one to find it, in production, on a money path."""

    def test_decimal_precio_unitario_is_accepted(self) -> None:
        shipping = ShipmentShippingCost(amount=3200.0)

        result = calcular_markup_pxq(
            precio_unitario=Decimal("500.00"),
            cantidad_minima=10,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(COSTO, 10),
            shipping=shipping,
        )

        assert result == pytest.approx(_expected(500.0, 10, 3200.0))

    def test_decimal_costo_is_accepted(self) -> None:
        shipping = ShipmentShippingCost(amount=3200.0)

        result = calcular_markup_pxq(
            precio_unitario=500.0,
            cantidad_minima=10,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(Decimal(str(COSTO)), 10),
            shipping=shipping,
        )

        assert result == pytest.approx(_expected(500.0, 10, 3200.0))

    def test_resolve_tier_shipping_accepts_a_decimal_column_value(self) -> None:
        tier = SimpleNamespace(costo_envio_total=Decimal("3200.00"))

        shipping = resolve_tier_shipping(tier)

        assert shipping is not None
        assert isinstance(shipping.amount, float)
        assert shipping.amount == pytest.approx(3200.0)


class TestGoldenCasesQuantityAwareMarkup:
    """1/5/10/30/70-unit tiers: the fixed low-price charge is bracketed on
    the order total, and shipping is subtracted once for the WHOLE
    shipment, never per-unit x N."""

    @pytest.mark.parametrize("cantidad_minima", [1, 5, 10, 30, 70])
    def test_matches_canonical_chain_on_order_total_and_whole_shipment(self, cantidad_minima: int) -> None:
        precio_unitario = 500.0
        envio_total = 3200.0  # whole-shipment cost, independent of quantity

        shipping = ShipmentShippingCost(amount=envio_total)
        result = calcular_markup_pxq(
            precio_unitario=precio_unitario,
            cantidad_minima=cantidad_minima,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(COSTO, cantidad_minima),
            shipping=shipping,
        )

        expected = _expected(precio_unitario, cantidad_minima, envio_total)
        assert result["precio_total"] == pytest.approx(expected["precio_total"])
        assert result["comision_total"] == pytest.approx(expected["comision_total"])
        assert result["limpio"] == pytest.approx(expected["limpio"])
        assert result["markup"] == pytest.approx(expected["markup"])


class TestRegressionNaivePerUnitShippingBug:
    """Explicitly reproduces the old bug shape: a naive caller that fed
    `calcular_limpio` a per-unit `costo_envio` (subtracted once per unit's
    computation, e.g. multiplied by N) would produce a DIFFERENT — and
    wrong — result than one that correctly subtracts the whole-shipment
    cost exactly once."""

    def test_correct_result_differs_from_naive_per_unit_times_n(self) -> None:
        # precio_total must clear MONTOT3 (envío gratis bracket) for
        # `calcular_limpio` to subtract shipping at all — otherwise the bug
        # is invisible regardless of which shipping value is fed in.
        precio_unitario = 5000.0
        cantidad_minima = 10
        costo_envio_unitario = 320.0  # per-unit cost the old (buggy) code used
        envio_total = costo_envio_unitario * cantidad_minima  # whole-shipment, correct

        shipping = ShipmentShippingCost(amount=envio_total)
        correct = calcular_markup_pxq(
            precio_unitario=precio_unitario,
            cantidad_minima=cantidad_minima,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(COSTO, cantidad_minima),
            shipping=shipping,
        )

        # Old bug shape: subtract the per-unit shipping cost only once from
        # the order total's `calcular_limpio`, instead of the whole-shipment
        # total — this silently under-charges shipping on any tier with
        # cantidad_minima > 1.
        precio_total = precio_unitario * cantidad_minima
        buggy_comisiones = calcular_comision_ml_total(precio_total, COMISION_BASE_PCT, IVA)
        buggy_limpio = calcular_limpio(precio_total, IVA, costo_envio_unitario, buggy_comisiones["comision_total"])
        buggy_markup = calcular_markup(buggy_limpio, COSTO)

        assert correct["limpio"] != pytest.approx(buggy_limpio)
        assert correct["markup"] != pytest.approx(buggy_markup)


class TestResolveTierShipping:
    def test_none_costo_envio_total_resolves_to_none(self) -> None:
        tier = _make_tier(cantidad_minima=5, costo_envio_total=None)
        assert resolve_tier_shipping(tier) is None

    def test_set_costo_envio_total_resolves_to_shipping_value_object(self) -> None:
        tier = _make_tier(cantidad_minima=5, costo_envio_total=1234.56)
        shipping = resolve_tier_shipping(tier)
        assert isinstance(shipping, ShipmentShippingCost)
        assert shipping.amount == pytest.approx(1234.56)

    def test_incomplete_tier_never_priced_no_fallback_to_per_unit_field(self) -> None:
        """A tier missing costo_envio_total must resolve to None — never
        falling back to any per-unit shipping field (e.g. producto.envio)."""
        tier = _make_tier(cantidad_minima=5, costo_envio_total=None)
        assert resolve_tier_shipping(tier) is None
        # There is no per-unit fallback path: the function only reads
        # `costo_envio_total`, so a bare producto.envio-shaped object can't
        # even be passed through it meaningfully.


class TestShippingParameterHasNoDefault:
    """Fail-closed by construction: the wrapper's shipping parameter must
    have NO default so a caller cannot silently omit it."""

    def test_shipping_parameter_has_no_default(self) -> None:
        sig = inspect.signature(calcular_markup_pxq)
        shipping_param = sig.parameters["shipping"]
        assert shipping_param.default is inspect.Parameter.empty

    def test_shipping_parameter_annotated_as_shipment_shipping_cost(self) -> None:
        sig = inspect.signature(calcular_markup_pxq)
        shipping_param = sig.parameters["shipping"]
        annotation = shipping_param.annotation
        annotation_name = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", annotation)
        assert annotation_name == "ShipmentShippingCost"


class TestBareFloatCannotSubstituteForShippingType:
    def test_shipment_shipping_cost_is_a_distinct_frozen_type(self) -> None:
        shipping = ShipmentShippingCost(amount=100.0)
        assert shipping.amount == 100.0
        with pytest.raises(FrozenInstanceError):
            shipping.amount = 200.0

    def test_a_bare_float_is_not_a_shipment_shipping_cost(self) -> None:
        bare_float = 3200.0
        assert not isinstance(bare_float, ShipmentShippingCost)


class TestGroupAverageFallbackIsUnreachable:
    """`calcular_limpio` swaps a zero `costo_envio` for the group's PER-UNIT
    average shipping when handed a `grupo_id` and a `db`. That is the exact
    fallback this module claims to make impossible, and a tier may legitimately
    carry `costo_envio_total = 0` (a shipment the seller does not pay for) —
    a real value, not the `None` that marks a tier incomplete.

    So the escape hatch is closed by not offering it: the wrapper does not
    accept `grupo_id` at all."""

    def test_wrapper_does_not_accept_grupo_id(self) -> None:
        parameters = inspect.signature(calcular_markup_pxq).parameters
        assert "grupo_id" not in parameters, (
            "exposing grupo_id lets calcular_limpio replace a zero whole-shipment "
            "cost with a per-unit group average, on the money path"
        )

    def test_zero_shipping_stays_zero(self) -> None:
        shipping = resolve_tier_shipping(SimpleNamespace(costo_envio_total=Decimal("0.00")))
        assert shipping is not None
        assert shipping.amount == 0.0

        result = calcular_markup_pxq(
            precio_unitario=Decimal("2000.00"),
            cantidad_minima=30,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(COSTO, 30),
            shipping=shipping,
        )

        assert result == pytest.approx(_expected(2000.0, 30, 0.0))


class TestGoldenValuesComputedIndependently:
    """The other golden cases call the same chain the implementation calls, so
    they prove the wrapper wires things up but not that the arithmetic is
    right — move the multiplication into `_expected` by mistake and both sides
    shift together.

    These numbers were worked out separately from MercadoLibre's documented
    rules (bracket on the ORDER TOTAL, fixed charge dropped at $33.000, whole
    shipment subtracted once and only above that threshold) and are hardcoded
    on purpose. If the implementation changes meaning, these fail; if it is
    merely refactored, they do not."""

    # (cantidad_minima, precio_total, comision_total, limpio, markup)
    GOLDEN = (
        (1, 500.0, 1014.4628099173555, -601.2396694214876, -1.6012396694214877),
        (5, 2500.0, 1452.4793388429753, 613.6363636363635, -0.8772727272727273),
        (10, 5000.0, 2000.0, 2132.2314049586776, -0.7867768595041322),
        (30, 15000.0, 5095.04132231405, 7301.652892561983, -0.7566115702479339),
        (70, 35000.0, 7665.289256198348, 18615.70247933884, -0.7340613931523023),
    )

    @pytest.mark.parametrize("cantidad_minima,precio_total,comision_total,limpio,markup", GOLDEN)
    def test_matches_independently_computed_values(
        self, cantidad_minima: int, precio_total: float, comision_total: float, limpio: float, markup: float
    ) -> None:
        result = calcular_markup_pxq(
            precio_unitario=500.0,
            cantidad_minima=cantidad_minima,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(COSTO, cantidad_minima),
            shipping=ShipmentShippingCost(amount=3200.0),
        )

        assert result["precio_total"] == pytest.approx(precio_total)
        assert result["comision_total"] == pytest.approx(comision_total)
        assert result["limpio"] == pytest.approx(limpio)
        assert result["markup"] == pytest.approx(markup)

    def test_the_seventy_unit_case_actually_exercises_the_shipping_subtraction(self) -> None:
        """A 1-unit tier at $500 never crosses the $33.000 threshold, so its
        shipping is not subtracted at all — that case cannot catch a shipping
        bug. This one can: 70 x $500 = $35.000 is above the threshold."""
        with_shipping = calcular_markup_pxq(
            precio_unitario=500.0,
            cantidad_minima=70,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(COSTO, 70),
            shipping=ShipmentShippingCost(amount=3200.0),
        )
        without_shipping = calcular_markup_pxq(
            precio_unitario=500.0,
            cantidad_minima=70,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(COSTO, 70),
            shipping=ShipmentShippingCost(amount=0.0),
        )

        # Exactly ONE whole shipment net of IVA, never 70 of them.
        assert without_shipping["limpio"] - with_shipping["limpio"] == pytest.approx(3200.0 / 1.21)


class TestOrderCostIsNotAPerUnitFloat:
    """`calcular_markup` divides the ORDER-level `limpio` by whatever it gets,
    so a per-unit cost inflates the markup by a factor of N. `costo` is the
    input a caller is most likely to fill from `producto.costo`, which is
    per-unit — the same unit-vs-order confusion the shipping side is already
    armoured against.

    The earlier golden cases encoded the bug: 70 units at $500 with a $1000
    cost produced a markup of 17.6 (1760%). That is not a possible number for
    selling below cost; it is the arithmetic signature of a per-unit cost
    measured against an order-level net."""

    def test_a_bare_float_cost_fails_loudly(self) -> None:
        with pytest.raises(AttributeError):
            calcular_markup_pxq(
                precio_unitario=500.0,
                cantidad_minima=70,
                comision_base_pct=COMISION_BASE_PCT,
                iva=IVA,
                costo=1000.0,  # per-unit, and deliberately not an OrderCost
                shipping=ShipmentShippingCost(amount=3200.0),
            )

    def test_resolve_order_cost_scales_by_quantity(self) -> None:
        assert resolve_order_cost(1000.0, 70).amount == pytest.approx(70_000.0)
        assert resolve_order_cost(Decimal("1000.00"), 30).amount == pytest.approx(30_000.0)

    def test_selling_below_cost_reports_a_loss_not_a_1760_percent_markup(self) -> None:
        result = calcular_markup_pxq(
            precio_unitario=500.0,
            cantidad_minima=70,
            comision_base_pct=COMISION_BASE_PCT,
            iva=IVA,
            costo=resolve_order_cost(1000.0, 70),
            shipping=ShipmentShippingCost(amount=3200.0),
        )

        # $500/unit against a $1000/unit cost is a loss, whatever the quantity.
        assert result["markup"] < 0
        assert result["markup"] == pytest.approx(-0.7340613931523023)


def test_a_wrong_object_raises_instead_of_looking_incomplete() -> None:
    """`getattr(..., None)` collapsed "this tier has no cost yet" — a real
    state the user resolves by filling it in — with "you handed me the wrong
    object". The second is a programmer error and has to be loud, or PR 3
    surfaces rows stuck on `incompleto` with nothing explaining why."""
    with pytest.raises(TypeError):
        resolve_tier_shipping(SimpleNamespace(precio_unitario=Decimal("500.00")))


def test_a_tier_with_no_cost_yet_is_still_incomplete_not_an_error() -> None:
    assert resolve_tier_shipping(SimpleNamespace(costo_envio_total=None)) is None

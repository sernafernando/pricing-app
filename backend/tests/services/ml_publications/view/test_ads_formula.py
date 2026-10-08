"""Ads-adjusted markup (addendum decisions 3, 5, 6). Pure: no database, no provider call."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.ml_publications.view.ads import (
    ADS_MARKUP_FORMULAS,
    STATE_ADS_SIN_VENTAS,
    STATE_OK,
    STATE_SIN_COSTO,
    AdsAvailability,
    UnavailableAdsProvider,
    ads_row,
    apply_ads,
    get_ads_provider,
    resolve_ads,
)
from app.services.ml_publications.view.markup import REASON_OK, UnitMarkup, aggregate_publication


def unit(limpio: float, costo: float) -> UnitMarkup:
    return UnitMarkup((limpio / costo - 1) * 100, REASON_OK, limpio, costo, 200.0, "item_price", 2)


class TestAdsRow:
    def test_per_unit_is_amount_over_units(self) -> None:
        row = ads_row(300.0, 10)
        assert (row.state, row.per_unit, row.amount, row.units) == (STATE_OK, 30.0, 300.0, 10)

    @pytest.mark.parametrize("amount", [0, 0.0, None])
    def test_no_cost_is_sin_costo(self, amount) -> None:
        row = ads_row(amount, 10)
        assert (row.state, row.per_unit) == (STATE_SIN_COSTO, 0.0)

    @pytest.mark.parametrize("units", [0, None, -2])
    def test_cost_without_units_is_ads_sin_ventas_and_keeps_the_amount(self, units) -> None:
        row = ads_row(300.0, units)
        assert (row.state, row.per_unit, row.amount) == (STATE_ADS_SIN_VENTAS, None, 300.0)

    def test_the_provider_amount_is_used_verbatim(self) -> None:
        """Decision 3: the figure is already net of IVA; nothing is converted here."""
        assert ads_row(121.0, 1).per_unit == 121.0


class TestApplyAds:
    def test_costo_extra_formula(self) -> None:
        pub = aggregate_publication(unit(150.0, 100.0), [])
        applied = apply_ads(pub, ads_row(200.0, 10), "costo_extra")  # per unit 20
        assert applied.markup.worst == pytest.approx((150.0 / 120.0 - 1) * 100)

    def test_resta_limpio_formula(self) -> None:
        pub = aggregate_publication(unit(150.0, 100.0), [])
        applied = apply_ads(pub, ads_row(200.0, 10), "resta_limpio")
        assert applied.markup.worst == pytest.approx(((150.0 - 20.0) / 100.0 - 1) * 100)

    def test_one_per_unit_value_is_applied_identically_to_every_variation(self) -> None:
        pub = aggregate_publication(None, [unit(150.0, 100.0), unit(130.0, 100.0), unit(90.0, 60.0)])
        applied = apply_ads(pub, ads_row(300.0, 10), "costo_extra")  # per unit 30 on all three
        expected = [(150 / 130 - 1) * 100, (130 / 130 - 1) * 100, (90 / 90 - 1) * 100]
        assert [v.value for v in applied.markup.variations] == pytest.approx(expected)
        assert applied.per_unit == 30.0
        assert applied.markup.worst == pytest.approx(min(expected))

    def test_negative_after_ads_is_flagged(self) -> None:
        pub = aggregate_publication(None, [unit(150.0, 100.0), unit(110.0, 100.0)])
        assert apply_ads(pub, ads_row(200.0, 10), "costo_extra").markup.any_negative is True

    def test_sin_costo_keeps_the_plain_markup(self) -> None:
        pub = aggregate_publication(unit(150.0, 100.0), [])
        applied = apply_ads(pub, ads_row(0, 10), "costo_extra")
        assert applied.markup is pub
        assert applied.state == STATE_SIN_COSTO

    def test_ads_sin_ventas_has_no_value_but_keeps_the_amount(self) -> None:
        pub = aggregate_publication(unit(150.0, 100.0), [])
        applied = apply_ads(pub, ads_row(300.0, 0), "costo_extra")
        assert applied.state == STATE_ADS_SIN_VENTAS
        assert (applied.markup.worst, applied.markup.value_min, applied.markup.value_max) == (None, None, None)
        assert applied.markup.reason == STATE_ADS_SIN_VENTAS
        assert applied.amount == 300.0

    def test_ads_sin_ventas_keeps_the_reason_of_a_variation_that_was_already_unusable(self) -> None:
        pub = aggregate_publication(None, [unit(150.0, 100.0), None])
        applied = apply_ads(pub, ads_row(300.0, 0), "costo_extra")
        assert [v.reason for v in applied.markup.variations] == [STATE_ADS_SIN_VENTAS, "sin_vinculo"]

    def test_ads_sin_ventas_does_not_hide_why_the_publication_had_no_markup_to_begin_with(self) -> None:
        pub = aggregate_publication(None, [None, None])
        applied = apply_ads(pub, ads_row(300.0, 0), "costo_extra")
        assert applied.markup.reason == "sin_vinculo"

    def test_a_formula_that_cannot_compute_leaves_no_value_and_a_reason(self) -> None:
        zero_cost = UnitMarkup(0.0, REASON_OK, 50.0, 0.0, 100.0, "item_price", 2)
        applied = apply_ads(aggregate_publication(zero_cost, []), ads_row(200.0, 10), "resta_limpio")
        unit_after = applied.markup.variations[0]
        assert (unit_after.value, unit_after.reason) == (None, "sin_costo")
        assert applied.markup.reason == "sin_costo"

    @pytest.mark.parametrize("name", sorted(ADS_MARKUP_FORMULAS))
    def test_a_zero_denominator_is_none(self, name) -> None:
        assert ADS_MARKUP_FORMULAS[name](50.0, 0.0, 0.0) is None

    def test_unusable_variations_stay_unusable(self) -> None:
        pub = aggregate_publication(None, [unit(150.0, 100.0), None])
        applied = apply_ads(pub, ads_row(200.0, 10), "costo_extra")
        assert applied.markup.variations[1].value is None
        assert applied.markup.partial == 1

    def test_unknown_formula_is_rejected(self) -> None:
        pub = aggregate_publication(unit(150.0, 100.0), [])
        with pytest.raises(ValueError):
            apply_ads(pub, ads_row(200.0, 10), "nope")


class TestProvider:
    def test_the_default_provider_is_unavailable(self) -> None:
        provider = get_ads_provider()
        assert isinstance(provider, UnavailableAdsProvider)
        assert provider.availability() is AdsAvailability.UNAVAILABLE
        assert provider.amounts(["MLA1"], date(2026, 9, 1), date(2026, 9, 30)) == {}
        assert provider.amounts(None, date(2026, 9, 1), date(2026, 9, 30)) == {}


class TestResolveAds:
    D1, D2 = date(2026, 9, 1), date(2026, 9, 30)

    class Provider:
        def __init__(self, availability=AdsAvailability.AVAILABLE, boom=False) -> None:
            self._availability, self._boom = availability, boom

        def availability(self):
            if self._boom:
                raise RuntimeError("down")
            return self._availability

    def test_an_unavailable_provider_is_reported_and_never_applied(self) -> None:
        status = resolve_ads(
            self.Provider(AdsAvailability.UNAVAILABLE), requested=True, date_from=self.D1, date_to=self.D2
        )
        assert (status.available, status.reason, status.requested, status.applied) == (
            False,
            "provider_missing",
            True,
            False,
        )

    def test_an_available_provider_is_applied_only_when_asked_for_with_a_period(self) -> None:
        provider = self.Provider()
        applied = resolve_ads(provider, requested=True, date_from=self.D1, date_to=self.D2)
        assert (applied.available, applied.applied, applied.date_from, applied.date_to) == (
            True,
            True,
            self.D1,
            self.D2,
        )
        assert resolve_ads(provider, requested=False, date_from=self.D1, date_to=self.D2).applied is False
        assert resolve_ads(provider, requested=True, date_from=None, date_to=None).applied is False

    def test_a_provider_that_raises_is_a_provider_that_is_not_there(self) -> None:
        status = resolve_ads(self.Provider(boom=True), requested=True, date_from=self.D1, date_to=self.D2)
        assert (status.available, status.reason, status.applied) == (False, "provider_error", False)

    def test_degrading_after_the_fact_keeps_what_was_asked(self) -> None:
        status = resolve_ads(self.Provider(), requested=True, date_from=self.D1, date_to=self.D2).degraded()
        assert (status.available, status.reason, status.requested, status.applied) == (
            False,
            "provider_error",
            True,
            False,
        )


def test_every_allowed_formula_name_has_an_implementation_and_vice_versa() -> None:
    from app.core.ads_formulas import ADS_FORMULA_NAMES

    assert set(ADS_FORMULA_NAMES) == set(ADS_MARKUP_FORMULAS)

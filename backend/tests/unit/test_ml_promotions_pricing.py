"""
Unit tests for `app.services.ml_promotions_pricing` (per-promo "nuestro
markup" enrichment).

Spec coverage:
  R2   — co-funding amount: SMART = meli%*original_price, else 0
  R1/R4 — effective discounted price / markup base per promo status
  R5/R6 — never crash: unresolvable publication/cost/price -> nuestro_markup=None
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services.ml_promotions_pricing import (
    _co_funding_amount,
    enriquecer_markup_por_promo,
    markup_para_precio,
    precio_de_oferta,
)
from app.services.ml_publications.view.markup import unit_markup
from app.services.ml_publications.view.markup_service import DetailUnit
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs


# ── precio_de_oferta ─────────────────────────────────────────────────

# Captured live DEAL entry, MLA1506729443 "MKP T1 CYBER MONDAY NOV" (2026-11-06). ML's web proposes it
# at its max (57920.55, the smallest discount ML accepts); the suggested 49266.65 is a deeper discount.
CAPTURED_DEAL = {
    "id": "P-MLA18145042",
    "type": "DEAL",
    "price": 0,
    "status": "candidate",
    "original_price": 86539,
    "max_discounted_price": 57920.55,
    "min_discounted_price": 17307.81,
    "suggested_discounted_price": 49266.65,
}


class TestPrecioDeOferta:
    def test_candidate_deal_uses_its_max(self) -> None:
        assert precio_de_oferta(CAPTURED_DEAL) == 57920.55

    def test_candidate_deal_mirror_row_shape_uses_its_max(self) -> None:
        row = {k: v for k, v in CAPTURED_DEAL.items() if k != "type"}
        row["promotion_type"] = "DEAL"
        assert precio_de_oferta(row) == 57920.55

    def test_candidate_deal_without_max_falls_back_to_suggested(self) -> None:
        promo = dict(CAPTURED_DEAL, max_discounted_price=None)
        assert precio_de_oferta(promo) == 49266.65

    def test_deal_with_a_price_keeps_it(self) -> None:
        assert precio_de_oferta(dict(CAPTURED_DEAL, price=55000)) == 55000

    def test_seller_campaign_keeps_the_suggested(self) -> None:
        promo = dict(CAPTURED_DEAL, type="SELLER_CAMPAIGN")
        assert precio_de_oferta(promo) == 49266.65

    # Captured LIGHTNING candidate, MLA1506729443 (2026-11-06): `price` 57920.55 is the SMART candidate's
    # price, not the lightning suggestion; the row shows the suggested 73558.15 (approved S9 build note).
    CAPTURED_LIGHTNING = {
        "promotion_id": "LGH-MLA1000",
        "promotion_type": "LIGHTNING",
        "status": "candidate",
        "price": 57920.55,
        "original_price": 86539.0,
        "min_discounted_price": 17307.81,
        "max_discounted_price": 77885.1,
        "suggested_discounted_price": 73558.15,
    }

    def test_candidate_lightning_uses_the_suggested(self) -> None:
        assert precio_de_oferta(self.CAPTURED_LIGHTNING) == 73558.15

    def test_candidate_lightning_live_shape_uses_the_suggested(self) -> None:
        live = {k: v for k, v in self.CAPTURED_LIGHTNING.items() if k != "promotion_type"}
        assert precio_de_oferta(dict(live, type="LIGHTNING")) == 73558.15

    def test_candidate_lightning_old_status_shape_uses_the_suggested(self) -> None:
        assert precio_de_oferta(dict(self.CAPTURED_LIGHTNING, status={"id": "candidate"})) == 73558.15

    def test_candidate_lightning_suggestion_above_the_max_is_shown_at_the_max(self) -> None:
        assert precio_de_oferta(dict(self.CAPTURED_LIGHTNING, suggested_discounted_price=80000)) == 77885.1

    def test_candidate_lightning_suggestion_below_the_min_is_shown_at_the_min(self) -> None:
        assert precio_de_oferta(dict(self.CAPTURED_LIGHTNING, suggested_discounted_price=10000)) == 17307.81

    def test_candidate_lightning_without_range_keeps_the_suggestion(self) -> None:
        promo = dict(self.CAPTURED_LIGHTNING, min_discounted_price=None, max_discounted_price=None)
        assert precio_de_oferta(promo) == 73558.15

    def test_candidate_lightning_without_suggestion_keeps_the_price(self) -> None:
        promo = dict(self.CAPTURED_LIGHTNING, suggested_discounted_price=None)
        assert precio_de_oferta(promo) == 57920.55

    def test_pending_lightning_keeps_its_price(self) -> None:
        promo = dict(self.CAPTURED_LIGHTNING, status="pending", price=70000)
        assert precio_de_oferta(promo) == 70000


# ── _co_funding_amount ───────────────────────────────────────────────


class TestCoFundingAmount:
    def test_smart_promo_computes_meli_share_of_original_price(self) -> None:
        promo = {
            "promotion_type": "SMART",
            "original_price": 28178,
            "payload": {"meli_percentage": 1.4},
        }
        co_funding = _co_funding_amount(promo)
        assert co_funding == pytest.approx(394.492, abs=1)

    def test_pre_negotiated_computes_meli_share_of_original_price(self) -> None:
        """PRE_NEGOTIATED co-funds exactly like SMART (parity)."""
        promo = {
            "promotion_type": "PRE_NEGOTIATED",
            "original_price": 28178,
            "payload": {"meli_percentage": 1.4},
        }
        co_funding = _co_funding_amount(promo)
        assert co_funding == pytest.approx(394.492, abs=1)

    def test_price_matching_computes_meli_share_of_original_price(self) -> None:
        """MUST-FIX (design D8): PRICE_MATCHING must co-fund like SMART,
        otherwise nuestro_markup is computed too low/wrong."""
        promo = {
            "promotion_type": "PRICE_MATCHING",
            "original_price": 28178,
            "payload": {"meli_percentage": 1.4},
        }
        co_funding = _co_funding_amount(promo)
        assert co_funding == pytest.approx(394.492, abs=1)
        assert co_funding != 0.0

    @pytest.mark.parametrize("promotion_type", ["SELLER_CAMPAIGN", "DEAL", "PRICE_DISCOUNT", "UNKNOWN_TYPE", None])
    def test_non_smart_types_have_zero_co_funding(self, promotion_type: str) -> None:
        promo = {
            "promotion_type": promotion_type,
            "original_price": 1000,
            "payload": {"meli_percentage": 10},
        }
        assert _co_funding_amount(promo) == 0.0

    def test_smart_missing_meli_percentage_returns_zero(self) -> None:
        promo = {"promotion_type": "SMART", "original_price": 1000, "payload": {}}
        assert _co_funding_amount(promo) == 0.0

    def test_smart_missing_original_price_returns_zero(self) -> None:
        promo = {"promotion_type": "SMART", "payload": {"meli_percentage": 5}}
        assert _co_funding_amount(promo) == 0.0

    def test_no_boost_fields_keeps_current_behavior(self) -> None:
        """(a) Absent boost fields: unchanged from meli_percentage share alone."""
        promo = {
            "promotion_type": "SMART",
            "original_price": 5000,
            "payload": {"meli_percentage": 8},
        }
        assert _co_funding_amount(promo) == pytest.approx(400.0)

    def test_boosted_offer_with_absolute_amount_uses_ml_official_example(self) -> None:
        """(b) boosted_offer=True + discount_meli_boost_amount -> add the
        absolute amount (ML's official worked example: 400 + 555 = 955)."""
        promo = {
            "promotion_type": "SMART",
            "original_price": 5000,
            "payload": {
                "meli_percentage": 8,
                "boosted_offer": True,
                "discount_meli_boosted_percentage": 11.1,
                "discount_meli_boost_amount": 555,
            },
        }
        assert _co_funding_amount(promo) == pytest.approx(955.0)

    def test_boosted_offer_without_absolute_amount_falls_back_to_percentage(self) -> None:
        """(c) boosted_offer=True, no discount_meli_boost_amount -> derive
        the boost from discount_meli_boosted_percentage * original_price."""
        promo = {
            "promotion_type": "SMART",
            "original_price": 5000,
            "payload": {
                "meli_percentage": 8,
                "boosted_offer": True,
                "discount_meli_boosted_percentage": 11.1,
            },
        }
        # 400 (meli_percentage share) + 555 (11.1% of 5000)
        assert _co_funding_amount(promo) == pytest.approx(955.0)

    def test_boost_fields_present_but_boosted_offer_falsy_is_ignored(self) -> None:
        """(d) boost fields present but boosted_offer absent/falsy -> no
        boost is added (ML documents the flag as the source of truth)."""
        promo = {
            "promotion_type": "SMART",
            "original_price": 5000,
            "payload": {
                "meli_percentage": 8,
                "discount_meli_boosted_percentage": 11.1,
                "discount_meli_boost_amount": 555,
            },
        }
        assert _co_funding_amount(promo) == pytest.approx(400.0)

    def test_boosted_offer_with_garbage_boost_values_adds_nothing(self) -> None:
        """(e) boosted_offer=True with unresolvable boost values (None or a
        non-numeric string) never raises and contributes 0.0 for the boost."""
        promo = {
            "promotion_type": "SMART",
            "original_price": 5000,
            "payload": {
                "meli_percentage": 8,
                "boosted_offer": True,
                "discount_meli_boost_amount": "not-a-number",
                "discount_meli_boosted_percentage": None,
            },
        }
        assert _co_funding_amount(promo) == pytest.approx(400.0)


# ── enriquecer_markup_por_promo ───────────────────────────────────────


# The pricing context is the publication's header unit (`markup_service.detail_unit`, S11): stubbed with the
# header's own pure inputs, the hand-built context of `test_unit_markup.py` and a unit costing 1000 ARS.
CTX = make_ctx()
UNIT = make_inputs(costo=1000.0, moneda_costo="ARS", iva=21.0)
ENVIO: dict[int, float] = {}
DETAIL_UNIT = "app.services.ml_promotions_pricing.detail_unit"


def _header_unit(ctx=CTX, unit=UNIT) -> DetailUnit:
    return DetailUnit(ctx, MagicMock(), MagicMock(), unit, None, ENVIO, None)


def _header(found: Optional[DetailUnit] = None):
    """Stubs the header unit lookup; `found` None stands for the default unit."""
    return patch(DETAIL_UNIT, return_value=found if found is not None else _header_unit())


def _expected_markup(revenue: float) -> float:
    """The header's markup of its unit at `revenue` (`unit_markup`, the header's own function)."""
    return unit_markup(CTX, replace(UNIT, sale_price=revenue), ENVIO).value


class TestEnriquecerMarkupPorPromo:
    def _run(self, db, mla, promos):
        with _header():
            return enriquecer_markup_por_promo(db, mla, promos)

    def test_smart_promo_markup_higher_than_ignoring_co_funding(self) -> None:
        db = MagicMock()

        smart_promo = {
            "promotion_type": "SMART",
            "status": "started",
            "price": 850,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {"meli_percentage": 10},
        }
        no_cofunding_promo = {
            "promotion_type": "SMART",
            "status": "started",
            "price": 850,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},  # no meli_percentage -> co_funding = 0
        }

        result = self._run(db, "MLA1", [smart_promo, no_cofunding_promo])

        assert result[0]["nuestro_markup"] is not None
        assert result[1]["nuestro_markup"] is not None
        assert result[0]["nuestro_markup"] > result[1]["nuestro_markup"]

    def test_seller_campaign_promo_markup_on_plain_price(self) -> None:
        db = MagicMock()

        promo = {
            "promotion_type": "SELLER_CAMPAIGN",
            "status": "started",
            "price": 800,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        result = self._run(db, "MLA1", [promo])
        assert result[0]["nuestro_markup"] is not None

    def test_candidate_promo_uses_suggested_discounted_price_as_base(self) -> None:
        db = MagicMock()

        candidate_promo = {
            "promotion_type": "DEAL",
            "status": "candidate",
            "price": 0,
            "original_price": 1000,
            "suggested_discounted_price": 900,
            "payload": {},
        }

        result = self._run(db, "MLA1", [candidate_promo])
        assert result[0]["nuestro_markup"] is not None

    def test_no_resolvable_publicacion_sets_all_none(self) -> None:
        db = MagicMock()
        promo = {
            "promotion_type": "DEAL",
            "status": "started",
            "price": 900,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        with patch(DETAIL_UNIT, return_value=None):
            result = enriquecer_markup_por_promo(db, "MLA_UNKNOWN", [promo])
        assert result[0]["nuestro_markup"] is None

    def test_producto_without_costo_sets_all_none(self) -> None:
        """No unit of the publication has a header markup (e.g. no cost): no promo markup either."""
        db = MagicMock()
        promo = {
            "promotion_type": "DEAL",
            "status": "started",
            "price": 900,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        with patch(DETAIL_UNIT, return_value=replace(_header_unit(), unit=None)):
            result = enriquecer_markup_por_promo(db, "MLA1", [promo])
        assert result[0]["nuestro_markup"] is None

    def test_promo_with_no_effective_price_sets_none_without_crash(self) -> None:
        db = MagicMock()

        promo = {
            "promotion_type": "DEAL",
            "status": "candidate",
            "price": 0,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        result = self._run(db, "MLA1", [promo])
        assert result[0]["nuestro_markup"] is None

    def test_empty_promo_list_returns_empty(self) -> None:
        db = MagicMock()
        assert enriquecer_markup_por_promo(db, "MLA1", []) == []

    def test_no_comision_base_sets_all_none(self) -> None:
        db = MagicMock()

        promo = {
            "promotion_type": "DEAL",
            "status": "started",
            "price": 900,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        with _header(_header_unit(ctx=make_ctx(comision_base={}))):
            result = enriquecer_markup_por_promo(db, "MLA1", [promo])

        assert result[0]["nuestro_markup"] is None


# ── Numeric parity with the header markup (S11) ───────────────────────
#
# These tests lock the FORMULA, not just "is not None": the expected markup is
# the header's own `unit_markup` of the same unit at the promo's revenue. A
# wrong revenue (co-funding dropped or applied on the markup) breaks them.


class TestNuestroMarkupNumericParity:
    def _run(self, db, mla, promos):
        with _header():
            return enriquecer_markup_por_promo(db, mla, promos)

    def _expected_markup(self, db, effective_revenue: float) -> float:
        return _expected_markup(effective_revenue)

    def test_non_smart_promo_matches_canonical_markup_on_effective_price(self) -> None:
        """No co-funding: nuestro_markup must equal the canonical markup
        computed on the plain effective (discounted) price."""
        db = MagicMock()

        effective_price = 800.0
        promo = {
            "promotion_type": "SELLER_CAMPAIGN",
            "status": "started",
            "price": effective_price,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        result = self._run(db, "MLA1", [promo])

        expected = self._expected_markup(db, effective_price)
        assert result[0]["nuestro_markup"] == pytest.approx(expected)

    def test_candidate_promo_matches_canonical_markup_on_suggested_price(self) -> None:
        db = MagicMock()

        suggested_price = 900.0
        promo = {
            "promotion_type": "DEAL",
            "status": "candidate",
            "price": 0,
            "original_price": 1000,
            "suggested_discounted_price": suggested_price,
            "payload": {},
        }

        result = self._run(db, "MLA1", [promo])

        expected = self._expected_markup(db, suggested_price)
        assert result[0]["nuestro_markup"] == pytest.approx(expected)

    def test_smart_promo_matches_canonical_markup_on_price_plus_co_funding(self) -> None:
        """SMART: nuestro_markup must equal the canonical markup computed on
        `effective_price + (meli_percentage / 100) * original_price` -- i.e.
        co-funding is ADDED to the base fed into the formula, not ignored and
        not applied on top of the resulting markup."""
        db = MagicMock()

        effective_price = 850.0
        original_price = 1000.0
        meli_percentage = 5.0
        co_funding = (meli_percentage / 100) * original_price  # 50.0

        promo = {
            "promotion_type": "SMART",
            "status": "started",
            "price": effective_price,
            "original_price": original_price,
            "suggested_discounted_price": None,
            "payload": {"meli_percentage": meli_percentage},
        }

        result = self._run(db, "MLA1", [promo])

        expected_with_cofunding = self._expected_markup(db, effective_price + co_funding)
        expected_without_cofunding = self._expected_markup(db, effective_price)

        # Sanity: co-funding must actually move the number, otherwise this
        # test could pass vacuously regardless of whether the service adds it.
        assert expected_with_cofunding != pytest.approx(expected_without_cofunding)

        assert result[0]["nuestro_markup"] == pytest.approx(expected_with_cofunding)
        assert result[0]["nuestro_markup"] != pytest.approx(expected_without_cofunding)

    def test_pre_negotiated_matches_canonical_markup_on_price_plus_co_funding(self) -> None:
        """PRE_NEGOTIATED must behave exactly like SMART: markup computed on
        effective_price + ML co-funding (meli_percentage * original_price),
        never on price alone."""
        db = MagicMock()

        effective_price = 850.0
        original_price = 1000.0
        meli_percentage = 5.0
        co_funding = (meli_percentage / 100) * original_price  # 50.0

        promo = {
            "promotion_type": "PRE_NEGOTIATED",
            "status": "started",
            "price": effective_price,
            "original_price": original_price,
            "suggested_discounted_price": None,
            "payload": {"meli_percentage": meli_percentage},
        }

        result = self._run(db, "MLA1", [promo])

        expected_with_cofunding = self._expected_markup(db, effective_price + co_funding)
        expected_without_cofunding = self._expected_markup(db, effective_price)

        assert expected_with_cofunding != pytest.approx(expected_without_cofunding)
        assert result[0]["nuestro_markup"] == pytest.approx(expected_with_cofunding)
        assert result[0]["nuestro_markup"] != pytest.approx(expected_without_cofunding)


# ── markup_para_precio ────────────────────────────────────────────────
#
# Reuses the same cost/pricelist/commission resolution as
# `enriquecer_markup_por_promo`, but computes the markup for an arbitrary
# candidate `price` (no co-funding — used by SELLER_CAMPAIGN/DEAL, which are
# seller-funded, so markup is computed on the plain price).


class TestMarkupParaPrecio:
    def _run(self, db, mla, price):
        with _header():
            return markup_para_precio(db, mla, price)

    def test_matches_canonical_markup_chain_for_a_known_price(self) -> None:
        db = MagicMock()
        price = 850.0
        result = self._run(db, "MLA1", price)

        assert result == pytest.approx(_expected_markup(price))

    def test_unresolvable_publicacion_returns_none(self) -> None:
        db = MagicMock()
        with patch(DETAIL_UNIT, return_value=None):
            assert markup_para_precio(db, "MLA_UNKNOWN", 850.0) is None

    def test_producto_without_costo_returns_none(self) -> None:
        db = MagicMock()
        with patch(DETAIL_UNIT, return_value=replace(_header_unit(), unit=None)):
            assert markup_para_precio(db, "MLA1", 850.0) is None

    def test_no_comision_base_returns_none(self) -> None:
        db = MagicMock()
        with _header(_header_unit(ctx=make_ctx(comision_base={}))):
            assert markup_para_precio(db, "MLA1", 850.0) is None

    def test_exception_in_calculation_returns_none_never_raises(self) -> None:
        db = MagicMock()
        with (
            _header(),
            patch("app.services.ml_promotions_pricing.unit_markup", side_effect=RuntimeError("boom")),
        ):
            assert markup_para_precio(db, "MLA1", 850.0) is None

    def test_a_failed_header_lookup_returns_none_never_raises(self) -> None:
        db = MagicMock()
        with patch(DETAIL_UNIT, side_effect=RuntimeError("store down")):
            assert markup_para_precio(db, "MLA1", 850.0) is None


# ── markup_baseline_vigente ───────────────────────────────────────


class TestMarkupBaselineVigente:
    """Baseline for hay_mejores: co-funded started vs plain sale.

    Mirror shape (store `raw`): flat ML entry — `meli_percentage` on the entry
    itself; ``markup_baseline_vigente`` uses ``payload=entry`` when nested
    payload is absent (same as ``normalizar_entrada_seller_promo``).
    """

    def _expected_markup(self, db, effective_revenue: float) -> float:
        return _expected_markup(effective_revenue)

    def test_uses_real_cofunded_chain_when_started_price_matches_sale(self) -> None:
        from app.services.ml_promotions_pricing import markup_baseline_vigente

        db = MagicMock()

        sale = 850.0
        original = 1000.0
        meli_percentage = 5.0
        # Flat mirror entry (no nested payload) — captured store shape.
        raw = [
            {
                "id": "P-MLA-LIVE",
                "type": "PRICE_MATCHING",
                "status": "started",
                "price": sale,
                "original_price": original,
                "meli_percentage": meli_percentage,
            },
            {
                "id": "P-MLA-SMART",
                "type": "SMART",
                "status": "candidate",
                "price": 800.0,
                "original_price": original,
            },
        ]
        co_funding = (meli_percentage / 100) * original
        expected = self._expected_markup(db, sale + co_funding)

        with _header():
            assert markup_baseline_vigente(db, "MLA1", sale + 0.5, raw_promotions=raw) == pytest.approx(expected)

    def test_falls_back_to_plain_markup_without_cofunded_started(self) -> None:
        from app.services.ml_promotions_pricing import markup_baseline_vigente

        db = MagicMock()
        raw = [
            {
                "id": "P-2",
                "type": "SMART",
                "status": "candidate",
                "price": 526957,
            },
            {
                "id": "C-1",
                "type": "SELLER_CAMPAIGN",
                "status": "started",
                "price": 599999,
            },
        ]
        with patch(
            "app.services.ml_promotions_pricing.markup_para_precio",
            return_value=-5.1,
        ) as plain:
            assert markup_baseline_vigente(db, "MLA1", 555867.83, raw_promotions=raw) == -5.1
            plain.assert_called_once_with(db, "MLA1", 555867.83)

    def test_falls_back_when_started_cofunded_price_does_not_match_sale(self) -> None:
        from app.services.ml_promotions_pricing import markup_baseline_vigente

        db = MagicMock()
        raw = [
            {
                "id": "P-1",
                "type": "PRICE_MATCHING",
                "status": "started",
                "price": 400000,
                "original_price": 939442,
                "meli_percentage": 10,
            },
        ]

        def _enrich(_db, _mla, promos):
            for promo in promos:
                promo["nuestro_markup"] = 1.4
            return promos

        with (
            patch("app.services.ml_promotions_pricing.enriquecer_markup_por_promo", side_effect=_enrich),
            patch("app.services.ml_promotions_pricing.markup_para_precio", return_value=-5.1) as plain,
        ):
            assert markup_baseline_vigente(db, "MLA1", 555867.83, raw_promotions=raw) == -5.1
            plain.assert_called_once()

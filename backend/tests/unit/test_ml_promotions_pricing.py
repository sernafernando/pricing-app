"""
Unit tests for `app.services.ml_promotions_pricing` (per-promo "nuestro
markup" enrichment).

Spec coverage:
  R2   — co-funding amount: SMART = meli%*original_price, else 0
  R1/R4 — effective discounted price / markup base per promo status
  R5/R6 — never crash: unresolvable publication/cost/price -> nuestro_markup=None
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.ml_promotions_pricing import (
    _co_funding_amount,
    _effective_discounted_price,
    enriquecer_markup_por_promo,
    markup_para_precio,
)
from app.services.pricing_calculator import (
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
)


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


# ── _effective_discounted_price ──────────────────────────────────────


class TestEffectiveDiscountedPrice:
    def test_started_promo_uses_price(self) -> None:
        promo = {"price": 850, "suggested_discounted_price": None}
        assert _effective_discounted_price(promo) == 850

    def test_candidate_promo_uses_suggested_discounted_price(self) -> None:
        promo = {"price": 0, "suggested_discounted_price": 900}
        assert _effective_discounted_price(promo) == 900

    def test_no_usable_price_returns_none(self) -> None:
        promo = {"price": 0, "suggested_discounted_price": None}
        assert _effective_discounted_price(promo) is None


# ── enriquecer_markup_por_promo ───────────────────────────────────────


def _make_producto(costo: float = 1000.0, moneda: str = "ARS", iva: float = 21.0, subcategoria_id: int = 1):
    producto = MagicMock()
    producto.item_id = 555
    producto.costo = costo
    producto.moneda_costo = moneda
    producto.iva = iva
    producto.subcategoria_id = subcategoria_id
    return producto


def _make_publicacion(item_id: int = 555, pricelist_id: int = 4):
    pub = MagicMock()
    pub.item_id = item_id
    pub.pricelist_id = pricelist_id
    return pub


class TestEnriquecerMarkupPorPromo:
    def _run(self, db, mla, promos):
        with (
            patch("app.services.ml_promotions_pricing.obtener_comision_base", return_value=20.0),
            patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0),
            patch("app.services.ml_promotions_pricing.obtener_grupo_subcategoria", return_value=1),
        ):
            return enriquecer_markup_por_promo(db, mla, promos)

    def test_smart_promo_markup_higher_than_ignoring_co_funding(self) -> None:
        db = MagicMock()
        producto = _make_producto()
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
        producto = _make_producto()
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
        producto = _make_producto()
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
        db.query.return_value.filter.return_value.first.side_effect = [None]

        promo = {
            "promotion_type": "DEAL",
            "status": "started",
            "price": 900,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        result = enriquecer_markup_por_promo(db, "MLA_UNKNOWN", [promo])
        assert result[0]["nuestro_markup"] is None

    def test_producto_without_costo_sets_all_none(self) -> None:
        db = MagicMock()
        producto = _make_producto(costo=None)
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

        promo = {
            "promotion_type": "DEAL",
            "status": "started",
            "price": 900,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        result = enriquecer_markup_por_promo(db, "MLA1", [promo])
        assert result[0]["nuestro_markup"] is None

    def test_promo_with_no_effective_price_sets_none_without_crash(self) -> None:
        db = MagicMock()
        producto = _make_producto()
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
        producto = _make_producto()
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

        promo = {
            "promotion_type": "DEAL",
            "status": "started",
            "price": 900,
            "original_price": 1000,
            "suggested_discounted_price": None,
            "payload": {},
        }

        with (
            patch("app.services.ml_promotions_pricing.obtener_comision_base", return_value=None),
            patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0),
            patch("app.services.ml_promotions_pricing.obtener_grupo_subcategoria", return_value=1),
        ):
            result = enriquecer_markup_por_promo(db, "MLA1", [promo])

        assert result[0]["nuestro_markup"] is None


# ── Numeric parity with the canonical /precios/calcular-markup chain ───
#
# These tests lock the FORMULA, not just "is not None". They compute the
# expected markup by calling the same canonical functions
# (`calcular_comision_ml_total` -> `calcular_limpio` -> `calcular_markup`)
# directly in the test, with the same resolved inputs (comision_base,
# iva, costo_envio, grupo_id, costo_ars) and the same `db` mock instance,
# then assert the service's `nuestro_markup` equals that value exactly.
# A wrong arg order, wrong base, or an extra *100 would break these.


class TestNuestroMarkupNumericParity:
    COMISION_BASE = 20.0
    COSTO_ENVIO = 0.0
    GRUPO_ID = 1
    COSTO = 1000.0
    IVA = 21.0

    def _run(self, db, mla, promos):
        with (
            patch("app.services.ml_promotions_pricing.obtener_comision_base", return_value=self.COMISION_BASE),
            patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=self.COSTO_ENVIO),
            patch("app.services.ml_promotions_pricing.obtener_grupo_subcategoria", return_value=self.GRUPO_ID),
        ):
            return enriquecer_markup_por_promo(db, mla, promos)

    def _expected_markup(self, db, effective_revenue: float) -> float:
        """Canonical chain used by `/precios/calcular-markup`, invoked directly
        with the same resolved inputs the service uses. Uses the SAME `db`
        mock instance so both the service call and this expectation resolve
        pricing constants identically (deterministic given the same mock)."""
        comisiones = calcular_comision_ml_total(effective_revenue, self.COMISION_BASE, self.IVA, db=db)
        limpio = calcular_limpio(
            effective_revenue,
            self.IVA,
            self.COSTO_ENVIO,
            comisiones["comision_total"],
            db=db,
            grupo_id=self.GRUPO_ID,
        )
        return calcular_markup(limpio, self.COSTO) * 100

    def test_non_smart_promo_matches_canonical_markup_on_effective_price(self) -> None:
        """No co-funding: nuestro_markup must equal the canonical markup
        computed on the plain effective (discounted) price."""
        db = MagicMock()
        producto = _make_producto(costo=self.COSTO, moneda="ARS", iva=self.IVA)
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
        producto = _make_producto(costo=self.COSTO, moneda="ARS", iva=self.IVA)
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
        producto = _make_producto(costo=self.COSTO, moneda="ARS", iva=self.IVA)
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
        producto = _make_producto(costo=self.COSTO, moneda="ARS", iva=self.IVA)
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

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
    COMISION_BASE = 20.0
    COSTO_ENVIO = 0.0
    GRUPO_ID = 1
    COSTO = 1000.0
    IVA = 21.0

    def _run(self, db, mla, price):
        with (
            patch("app.services.ml_promotions_pricing.obtener_comision_base", return_value=self.COMISION_BASE),
            patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=self.COSTO_ENVIO),
            patch("app.services.ml_promotions_pricing.obtener_grupo_subcategoria", return_value=self.GRUPO_ID),
        ):
            return markup_para_precio(db, mla, price)

    def test_matches_canonical_markup_chain_for_a_known_price(self) -> None:
        db = MagicMock()
        producto = _make_producto(costo=self.COSTO, moneda="ARS", iva=self.IVA)
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

        price = 850.0
        result = self._run(db, "MLA1", price)

        comisiones = calcular_comision_ml_total(price, self.COMISION_BASE, self.IVA, db=db)
        limpio = calcular_limpio(
            price, self.IVA, self.COSTO_ENVIO, comisiones["comision_total"], db=db, grupo_id=self.GRUPO_ID
        )
        expected = calcular_markup(limpio, self.COSTO) * 100
        assert result == pytest.approx(expected)

    def test_unresolvable_publicacion_returns_none(self) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [None]
        assert markup_para_precio(db, "MLA_UNKNOWN", 850.0) is None

    def test_producto_without_costo_returns_none(self) -> None:
        db = MagicMock()
        producto = _make_producto(costo=None)
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]
        assert markup_para_precio(db, "MLA1", 850.0) is None

    def test_no_comision_base_returns_none(self) -> None:
        db = MagicMock()
        producto = _make_producto()
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

        with (
            patch("app.services.ml_promotions_pricing.obtener_comision_base", return_value=None),
            patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0),
            patch("app.services.ml_promotions_pricing.obtener_grupo_subcategoria", return_value=1),
        ):
            assert markup_para_precio(db, "MLA1", 850.0) is None

    def test_exception_in_calculation_returns_none_never_raises(self) -> None:
        db = MagicMock()
        producto = _make_producto()
        publicacion = _make_publicacion()
        db.query.return_value.filter.return_value.first.side_effect = [publicacion, producto]

        with (
            patch("app.services.ml_promotions_pricing.obtener_comision_base", return_value=self.COMISION_BASE),
            patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=self.COSTO_ENVIO),
            patch("app.services.ml_promotions_pricing.obtener_grupo_subcategoria", return_value=self.GRUPO_ID),
            patch("app.services.ml_promotions_pricing.calcular_comision_ml_total", side_effect=RuntimeError("boom")),
        ):
            assert markup_para_precio(db, "MLA1", 850.0) is None

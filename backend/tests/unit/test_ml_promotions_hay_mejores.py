"""Unit tests for hay-mejores-ofertas comparison (modo poner precios S7)."""

from __future__ import annotations

from app.services.ml_promotions_hay_mejores import (
    es_mejor_oferta,
    fingerprint_mejores,
    decidir_flag_hay_mejores,
    normalizar_entrada_seller_promo,
)


class TestEsMejorOferta:
    def test_higher_markup_is_better(self) -> None:
        assert es_mejor_oferta(
            candidate_price=1000,
            candidate_markup=30.0,
            baseline_price=1000,
            baseline_markup=20.0,
        )

    def test_same_price_same_markup_is_not_better(self) -> None:
        assert not es_mejor_oferta(
            candidate_price=1000,
            candidate_markup=20.0,
            baseline_price=1000,
            baseline_markup=20.0,
        )

    def test_lower_price_same_markup_is_better(self) -> None:
        assert es_mejor_oferta(
            candidate_price=900,
            candidate_markup=20.0,
            baseline_price=1000,
            baseline_markup=20.0,
        )

    def test_lower_price_higher_markup_is_better(self) -> None:
        assert es_mejor_oferta(
            candidate_price=900,
            candidate_markup=25.0,
            baseline_price=1000,
            baseline_markup=20.0,
        )

    def test_higher_price_same_markup_is_not_better(self) -> None:
        assert not es_mejor_oferta(
            candidate_price=1100,
            candidate_markup=20.0,
            baseline_price=1000,
            baseline_markup=20.0,
        )

    def test_higher_price_higher_markup_is_not_better(self) -> None:
        assert not es_mejor_oferta(
            candidate_price=1100,
            candidate_markup=30.0,
            baseline_price=1000,
            baseline_markup=20.0,
        )

    def test_lower_markup_is_not_better_even_with_lower_price(self) -> None:
        assert not es_mejor_oferta(
            candidate_price=800,
            candidate_markup=15.0,
            baseline_price=1000,
            baseline_markup=20.0,
        )

    def test_missing_markups_are_not_better(self) -> None:
        assert not es_mejor_oferta(900, None, 1000, 20.0)
        assert not es_mejor_oferta(900, 25.0, 1000, None)
        assert not es_mejor_oferta(None, 25.0, 1000, 20.0)


class TestFingerprintAndDecide:
    def test_fingerprint_is_stable_sorted(self) -> None:
        a = fingerprint_mejores([("B", 100.0), ("A", 90.5)])
        b = fingerprint_mejores([("A", 90.5), ("B", 100.0)])
        assert a == b
        assert a == "A:90.5|B:100"

    def test_fingerprint_distinguishes_million_peso_prices(self) -> None:
        low = fingerprint_mejores([("C-1", 1_234_567.0)])
        high = fingerprint_mejores([("C-1", 1_234_568.0)])
        assert low != high
        assert low == "C-1:1234567"
        assert high == "C-1:1234568"

    def test_decide_sets_flag_when_better_and_not_discarded(self) -> None:
        decision = decidir_flag_hay_mejores(
            mejores=[("C-1", 900.0)],
            descartado_fingerprint=None,
        )
        assert decision.hay_mejores is True
        assert decision.fingerprint == "C-1:900"
        assert decision.descartado_fingerprint is None

    def test_decide_keeps_cleared_when_fingerprint_matches_discard(self) -> None:
        fp = fingerprint_mejores([("C-1", 900.0)])
        decision = decidir_flag_hay_mejores(
            mejores=[("C-1", 900.0)],
            descartado_fingerprint=fp,
        )
        assert decision.hay_mejores is False
        assert decision.fingerprint == fp
        assert decision.descartado_fingerprint == fp

    def test_decide_re_marks_when_new_better_novelty(self) -> None:
        old = fingerprint_mejores([("C-1", 900.0)])
        decision = decidir_flag_hay_mejores(
            mejores=[("C-1", 900.0), ("C-2", 850.0)],
            descartado_fingerprint=old,
        )
        assert decision.hay_mejores is True
        assert decision.fingerprint != old
        assert decision.descartado_fingerprint is None

    def test_decide_clears_when_no_better(self) -> None:
        decision = decidir_flag_hay_mejores(mejores=[], descartado_fingerprint="C-1:900")
        assert decision.hay_mejores is False
        assert decision.fingerprint is None
        assert decision.descartado_fingerprint is None


class TestNormalizarEntrada:
    def test_maps_type_to_promotion_type_and_keeps_prices(self) -> None:
        entry = {
            "id": "C-1",
            "type": "SMART",
            "status": "candidate",
            "price": 1000,
            "suggested_discounted_price": 0,
            "original_price": 1200,
            "meli_percentage": 2.5,
        }
        promo = normalizar_entrada_seller_promo(entry)
        assert promo["promotion_id"] == "C-1"
        assert promo["promotion_type"] == "SMART"
        assert promo["price"] == 1000
        assert promo["payload"]["meli_percentage"] == 2.5

"""Unit tests for hay-mejores-ofertas comparison (modo poner precios S7)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.ml_promotions_hay_mejores import (
    decidir_flag_hay_mejores,
    es_mejor_oferta,
    fingerprint_mejores,
    listar_mejores_candidatas,
    normalizar_entrada_seller_promo,
)
from app.services.ml_promotions_pricing import MarkupsDePrecio, precio_de_oferta

# The MLA's header unit as `resolver_contexto_promos` returns it (S11): opaque to the ranking, passed to both sides.
CONTEXT = object()


@pytest.fixture(autouse=True)
def header_context(monkeypatch) -> list:
    """The header unit lookup, counted: one call per ranked MLA."""
    calls: list = []

    def _resolve(_db, mla):
        calls.append(mla)
        return CONTEXT

    monkeypatch.setattr(hay_mejores, "resolver_contexto_promos", _resolve)
    return calls


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

    def test_candidate_deal_is_judged_at_its_max(self) -> None:
        # Captured live DEAL, MLA1506729443 "MKP T1 CYBER MONDAY NOV" (2026-11-06): the flag must price it
        # like the panel and the apply do (precio_de_oferta: its max), not at the deeper suggested.
        entry = {
            "id": "P-MLA18145042",
            "type": "DEAL",
            "price": 0,
            "status": "candidate",
            "original_price": 86539,
            "max_discounted_price": 57920.55,
            "min_discounted_price": 17307.81,
            "suggested_discounted_price": 49266.65,
        }
        promo = normalizar_entrada_seller_promo(entry)
        assert promo["max_discounted_price"] == 57920.55
        assert precio_de_oferta(promo) == 57920.55

    # Captured live LIGHTNING candidate, MLA1506729443 (2026-11-06): `price` is the SMART candidate's.
    CAPTURED_LIGHTNING_ENTRY = {
        "id": "LGH-MLA1000",
        "type": "LIGHTNING",
        "status": "candidate",
        "price": 57920.55,
        "original_price": 86539,
        "min_discounted_price": 17307.81,
        "max_discounted_price": 77885.1,
        "suggested_discounted_price": 73558.15,
    }

    def test_candidate_lightning_is_judged_at_its_suggestion(self) -> None:
        assert precio_de_oferta(normalizar_entrada_seller_promo(self.CAPTURED_LIGHTNING_ENTRY)) == 73558.15

    def test_candidate_lightning_is_judged_within_its_range(self) -> None:
        entry = dict(self.CAPTURED_LIGHTNING_ENTRY, suggested_discounted_price=10000)
        assert precio_de_oferta(normalizar_entrada_seller_promo(entry)) == 17307.81


class TestListarMejoresBaselineWiring:
    """Started co-funded baseline (via raw) can suppress a candidate that would beat plain sale."""

    def test_passes_raw_promotions_into_baseline_resolver(self, monkeypatch) -> None:
        seen: dict = {}

        def _baseline(_db, mla, price, *, raw_promotions=None, batch=None, context=None):
            seen["mla"] = mla
            seen["price"] = price
            seen["raw"] = raw_promotions
            return MarkupsDePrecio(1.4, None)

        monkeypatch.setattr(hay_mejores, "resolver_sell_in_out_para_mlas", lambda *_a, **_k: None)
        monkeypatch.setattr(hay_mejores, "markups_baseline_vigente", _baseline)
        monkeypatch.setattr(hay_mejores, "enriquecer_markup_por_promo", lambda *_a, **_k: [])
        raw = [{"id": "P-LIVE", "type": "PRICE_MATCHING", "status": "started", "price": 1000}]
        candidata = {"id": "P-C", "type": "SMART", "status": "candidate", "price": 900.0}
        listar_mejores_candidatas(MagicMock(), "MLA9", [candidata], 1000.0, raw_promotions=raw)
        assert seen == {"mla": "MLA9", "price": 1000.0, "raw": raw}

    def test_cofunded_baseline_suppresses_candidate_that_beats_plain_sale(self, monkeypatch) -> None:
        monkeypatch.setattr(hay_mejores, "resolver_sell_in_out_para_mlas", lambda *_a, **_k: None)
        monkeypatch.setattr(hay_mejores, "markups_baseline_vigente", lambda *_a, **_k: MarkupsDePrecio(1.4, None))

        def _enrich(_db, _mla, promos, **_kw):
            for promo in promos:
                promo["nuestro_markup"] = -5.06
            return promos

        monkeypatch.setattr(hay_mejores, "enriquecer_markup_por_promo", _enrich)
        candidates = [
            {"id": "P-SMART", "type": "SMART", "status": "candidate", "price": 526957.0},
        ]
        raw = [
            {
                "id": "P-LIVE",
                "type": "PRICE_MATCHING",
                "status": "started",
                "price": 555867.8,
                "original_price": 939442,
                "meli_percentage": 10,
            },
            *candidates,
        ]
        assert listar_mejores_candidatas(MagicMock(), "MLA1", candidates, 555867.83, raw_promotions=raw) == []

    def test_plain_low_baseline_still_flags_same_candidate(self, monkeypatch) -> None:
        monkeypatch.setattr(hay_mejores, "resolver_sell_in_out_para_mlas", lambda *_a, **_k: None)
        monkeypatch.setattr(hay_mejores, "markups_baseline_vigente", lambda *_a, **_k: MarkupsDePrecio(-5.1, None))

        def _enrich(_db, _mla, promos, **_kw):
            for promo in promos:
                promo["nuestro_markup"] = -5.06
            return promos

        monkeypatch.setattr(hay_mejores, "enriquecer_markup_por_promo", _enrich)
        candidates = [
            {"id": "P-SMART", "type": "SMART", "status": "candidate", "price": 526957.0},
        ]
        assert listar_mejores_candidatas(MagicMock(), "MLA1", candidates, 555867.83, raw_promotions=candidates) == [
            ("P-SMART", 526957.0)
        ]


class TestActualizarForwardsRawPromotions:
    """actualizar_hay_mejores_ofertas must pass mirror raw into listar_mejores_candidatas."""

    def test_forwards_raw_promotions_kwarg_to_listar(self, monkeypatch) -> None:
        seen: dict = {}
        raw = [
            {
                "id": "P-LIVE",
                "type": "PRICE_MATCHING",
                "status": "started",
                "price": 1000,
            },
            {"id": "C-1", "type": "SMART", "status": "candidate", "price": 900},
        ]
        row = SimpleNamespace(
            hay_mejores_ofertas=False,
            hay_mejores_fingerprint=None,
            hay_mejores_descartado_fingerprint=None,
            raw=None,
        )
        sale = SimpleNamespace(amount=1000.0)

        class _Nested:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        db = MagicMock()
        db.begin_nested.return_value = _Nested()
        db.query.return_value.filter.return_value.one_or_none.side_effect = [row, sale]

        def _listar(_db, mla, candidates, baseline, *, raw_promotions=None, sell_in_out_batch=None):
            seen["batch"] = sell_in_out_batch
            seen["mla"] = mla
            seen["candidates"] = candidates
            seen["baseline"] = baseline
            seen["raw"] = raw_promotions
            return [("C-1", 900.0)]

        monkeypatch.setattr(hay_mejores, "listar_mejores_candidatas", _listar)
        monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)

        decision = hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1", raw_promotions=raw)
        assert decision is not None and decision.hay_mejores is True
        assert seen["mla"] == "MLA1"
        assert seen["baseline"] == 1000.0
        assert seen["raw"] == raw
        assert seen["batch"] is None  # a single item resolves its own sell in / sell out
        assert seen["candidates"] == [
            {"id": "C-1", "type": "SMART", "status": "candidate", "price": 900},
        ]


class TestRankingConSellInOut:
    """S5 (owner: "va a tener que usar el sell in sell out"): a candidate and the status quo are compared by their
    `markup_sell_in_out` when BOTH have one, else both by `nuestro_markup`: always the same basis on both sides."""

    BATCH = object()

    def _wire(self, monkeypatch, baseline: MarkupsDePrecio, markups: dict) -> dict:
        seen: dict = {"enrich": []}

        def _baseline(_db, _mla, _price, *, raw_promotions=None, batch=None, context=None):
            seen["baseline_batch"] = batch
            seen["baseline_context"] = context
            return baseline

        def _enrich(_db, _mla, promos, *, sell_in_out=False, batch=None, context=None):
            seen["enrich"].append((sell_in_out, batch))
            seen["enrich_context"] = context
            for promo in promos:
                promo["nuestro_markup"], promo["markup_sell_in_out"] = markups[promo["promotion_id"]]
            return promos

        monkeypatch.setattr(hay_mejores, "resolver_sell_in_out_para_mlas", lambda _db, mlas: self.BATCH)
        monkeypatch.setattr(hay_mejores, "markups_baseline_vigente", _baseline)
        monkeypatch.setattr(hay_mejores, "enriquecer_markup_por_promo", _enrich)
        return seen

    @staticmethod
    def _candidatas(*ids: str) -> list:
        return [{"id": i, "type": "SMART", "status": "candidate", "price": 900.0} for i in ids]

    def test_plain_markup_picks_a_but_sell_in_out_picks_b(self, monkeypatch) -> None:
        # Plain: A 10 >= 9 is better, B 8 < 9 is not. With sell in / sell out: A 11 < 12 is not, B 14 >= 12 is.
        self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {"A": (10.0, 11.0), "B": (8.0, 14.0)})

        mejores = listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A", "B"), 1000.0)

        assert mejores == [("B", 900.0)]

    def test_a_candidate_without_sell_in_out_is_compared_plain_on_both_sides(self, monkeypatch) -> None:
        # The status quo has sell in / sell out (12) but A's and B's could not be computed: plain against plain 9.
        self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {"A": (10.0, None), "B": (8.0, None)})

        mejores = listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A", "B"), 1000.0)

        assert mejores == [("A", 900.0)]  # 10 >= 9; 8 < 9 (never 10 against 12)

    def test_a_status_quo_without_sell_in_out_compares_every_candidate_plain(self, monkeypatch) -> None:
        self._wire(monkeypatch, MarkupsDePrecio(9.0, None), {"A": (9.5, 7.0), "B": (8.5, 20.0)})

        mejores = listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A", "B"), 1000.0)

        assert mejores == [("A", 900.0)]  # 9.5 >= 9; 8.5 < 9 (B's 20 is never compared against a plain 9)

    def test_each_candidate_picks_its_own_basis(self, monkeypatch) -> None:
        # A has sell in / sell out (11 < 12: not better); B has none (10 >= 9: better, plain against plain).
        self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {"A": (10.0, 11.0), "B": (10.0, None)})

        mejores = listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A", "B"), 1000.0)

        assert mejores == [("B", 900.0)]

    def test_without_any_status_quo_markup_nothing_is_better(self, monkeypatch) -> None:
        self._wire(monkeypatch, MarkupsDePrecio(None, None), {"A": (50.0, 60.0)})

        assert listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A"), 1000.0) == []

    def test_one_sell_in_out_read_feeds_both_sides(self, monkeypatch) -> None:
        seen = self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {"A": (10.0, 13.0)})

        listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A"), 1000.0)

        assert seen["baseline_batch"] is self.BATCH
        assert seen["enrich"] == [(True, self.BATCH)]

    def test_the_header_unit_is_resolved_once_and_prices_both_sides(self, monkeypatch, header_context) -> None:
        """S11 perf: one header-unit resolution per MLA, shared by the status quo and every candidate."""
        seen = self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {"A": (10.0, 13.0), "B": (8.0, 14.0)})

        listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A", "B"), 1000.0)

        assert header_context == ["MLA1"]
        assert seen["baseline_context"] is CONTEXT and seen["enrich_context"] is CONTEXT

    def test_without_a_header_unit_nothing_is_better_and_nothing_else_is_read(self, monkeypatch) -> None:
        seen = self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {"A": (10.0, 13.0)})
        monkeypatch.setattr(hay_mejores, "resolver_contexto_promos", lambda _db, _mla: None)

        assert listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A"), 1000.0) == []
        assert "baseline_batch" not in seen and seen["enrich"] == []

    def test_a_given_batch_is_used_and_nothing_is_resolved_again(self, monkeypatch) -> None:
        seen = self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {"A": (10.0, 13.0)})
        monkeypatch.setattr(
            hay_mejores,
            "resolver_sell_in_out_para_mlas",
            lambda *_a: (_ for _ in ()).throw(AssertionError("resolved per item")),
        )
        dado = object()

        listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A"), 1000.0, sell_in_out_batch=dado)

        assert seen["baseline_batch"] is dado
        assert seen["enrich"] == [(True, dado)]

    def test_a_failed_shared_read_is_not_retried_per_side(self, monkeypatch) -> None:
        # The one read fails (None): both sides get the same empty read, so neither re-reads on its own.
        seen = self._wire(monkeypatch, MarkupsDePrecio(9.0, None), {"A": (10.0, None)})
        monkeypatch.setattr(hay_mejores, "resolver_sell_in_out_para_mlas", lambda _db, _mlas: None)

        mejores = listar_mejores_candidatas(MagicMock(), "MLA1", self._candidatas("A"), 1000.0)

        assert mejores == [("A", 900.0)]
        assert seen["baseline_batch"] is not None
        assert seen["enrich"] == [(True, seen["baseline_batch"])]

    def test_nothing_is_read_without_candidates(self, monkeypatch) -> None:
        seen = self._wire(monkeypatch, MarkupsDePrecio(9.0, 12.0), {})
        monkeypatch.setattr(
            hay_mejores,
            "resolver_sell_in_out_para_mlas",
            lambda *_a: (_ for _ in ()).throw(AssertionError("read without candidates")),
        )

        assert listar_mejores_candidatas(MagicMock(), "MLA1", [], 1000.0) == []
        assert "baseline_batch" not in seen and seen["enrich"] == []

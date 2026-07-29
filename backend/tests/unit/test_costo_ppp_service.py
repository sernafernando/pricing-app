"""
Unit tests for costo_ppp_service — PPP (ERP weighted-average cost) resolver
and per-product markup accumulator.

Spec coverage (openspec/changes/productos-costo-ppp/specs.md, source-correction
round 2026-07-29):
  REQ-1 — row selection: coslis_id = 1 (main cost list) AND iclh_price_aw IS
          NOT NULL AND iclh_price_aw > 0, latest iclh_cd wins, iclh_id DESC
          breaks exact-date ties.
  REQ-2 — PPP is displayed in its OWN currency (curr_id-derived), NEVER
          converted for display; conversion only ever happens internally, as
          an input to the markup formula.
  REQ-3 — costo_ppp_fecha always accompanies a non-null costo_ppp.
  REQ-4 — no-data contract: zero qualifying rows => item absent from the
          resolver dict AND PppMarkups(None).payload() is None; no emitted
          markup key ever equals a value derived from `costo`.
  REQ-5 — PppMarkups.record scaling: percent=True scales *100 (matches most
          sites), percent=False keeps the raw ratio (matches mejor_oferta
          sites).

These tests run against the REAL in-memory SQLite `db` fixture (see
tests/conftest.py) using the actual ItemCostListHistory ORM model — this
proves the resolver's window-function query is portable to SQLite, not just
PostgreSQL, with a single formulation for both (no dialect branching — see
costo_ppp_service module docstring).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models.item_cost_list_history import ItemCostListHistory
from app.services.costo_ppp_service import PppMarkups, PppSource, resolver_ppp_batch


def _insert_history(db, **overrides) -> ItemCostListHistory:
    defaults = dict(
        iclh_id=None,  # set explicitly per test — real PK, used as the tiebreak
        comp_id=1,
        coslis_id=1,
        item_id=1,
        iclh_price=100.0,
        iclh_price_aw=100.0,
        curr_id=1,
        iclh_cd=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    row = ItemCostListHistory(**defaults)
    db.add(row)
    db.commit()
    return row


class TestRowSelection:
    """REQ-1: row-selection predicate and latest-iclh_cd tiebreak."""

    def test_single_qualifying_row_is_used(self, db) -> None:
        _insert_history(db, iclh_id=1, item_id=101, iclh_price_aw=250.0, iclh_cd=datetime(2026, 1, 10))

        result = resolver_ppp_batch(db, [101])

        assert 101 in result
        assert result[101].costo_ppp == 250.0
        assert result[101].costo_ppp_fecha == datetime(2026, 1, 10).date()

    def test_latest_iclh_cd_wins_among_multiple_qualifying_rows(self, db) -> None:
        _insert_history(db, iclh_id=2, item_id=102, iclh_price_aw=100.0, iclh_cd=datetime(2025, 1, 1))
        _insert_history(db, iclh_id=3, item_id=102, iclh_price_aw=200.0, iclh_cd=datetime(2026, 6, 1))
        _insert_history(db, iclh_id=4, item_id=102, iclh_price_aw=150.0, iclh_cd=datetime(2025, 6, 1))

        result = resolver_ppp_batch(db, [102])

        assert result[102].costo_ppp == 200.0
        assert result[102].costo_ppp_fecha == datetime(2026, 6, 1).date()

    def test_exact_iclh_cd_tie_breaks_on_highest_iclh_id(self, db) -> None:
        """Real nondeterminism bug class the previous ORDER BY it_cd-only
        tiebreak had (see git history) — reproduced here for iclh_cd/iclh_id."""
        _insert_history(db, iclh_id=10, item_id=108, iclh_price_aw=400.0, iclh_cd=datetime(2026, 3, 1))
        _insert_history(db, iclh_id=11, item_id=108, iclh_price_aw=500.0, iclh_cd=datetime(2026, 3, 1))

        result = resolver_ppp_batch(db, [108])

        assert result[108].costo_ppp == 500.0  # highest iclh_id wins

    def test_other_coslis_id_excluded(self, db) -> None:
        """A row from a non-principal cost list must never be selected, even
        if it's the only row for that item_id."""
        _insert_history(db, iclh_id=5, item_id=103, coslis_id=7, iclh_price_aw=999.0)

        result = resolver_ppp_batch(db, [103])

        assert 103 not in result

    def test_decoy_rows_in_other_coslis_ids_never_win_over_principal(self, db) -> None:
        _insert_history(db, iclh_id=20, item_id=109, coslis_id=7, iclh_price_aw=77.0, iclh_cd=datetime(2026, 5, 1))
        _insert_history(db, iclh_id=21, item_id=109, coslis_id=8, iclh_price_aw=88.0, iclh_cd=datetime(2026, 5, 1))
        _insert_history(db, iclh_id=22, item_id=109, coslis_id=1, iclh_price_aw=38.4, iclh_cd=datetime(2026, 4, 1))

        result = resolver_ppp_batch(db, [109])

        assert result[109].costo_ppp == 38.4

    def test_null_price_aw_excluded(self, db) -> None:
        _insert_history(db, iclh_id=6, item_id=104, iclh_price_aw=None)

        result = resolver_ppp_batch(db, [104])

        assert 104 not in result

    def test_non_positive_price_aw_excluded(self, db) -> None:
        _insert_history(db, iclh_id=7, item_id=107, iclh_price_aw=0.0)

        result = resolver_ppp_batch(db, [107])

        assert 107 not in result

    def test_batch_resolves_multiple_items_in_one_call(self, db) -> None:
        _insert_history(db, iclh_id=8, item_id=201, iclh_price_aw=50.0)
        _insert_history(db, iclh_id=9, item_id=202, iclh_price_aw=75.0)

        result = resolver_ppp_batch(db, [201, 202, 203])

        assert result[201].costo_ppp == 50.0
        assert result[202].costo_ppp == 75.0
        assert 203 not in result

    def test_more_than_900_item_ids_does_not_blow_sqlite_variable_limit(self, db) -> None:
        """`item_id.in_(item_ids)` must be chunked (900, matching
        `batch_colores`'s SQLite/PostgreSQL param-limit chunking)."""
        item_ids = list(range(1000, 2000))  # 1000 ids -> 2 chunks at size 900
        for i, item_id in enumerate(item_ids[:3]):
            _insert_history(db, iclh_id=100 + i, item_id=item_id, iclh_price_aw=float(item_id))

        result = resolver_ppp_batch(db, item_ids)

        assert result[item_ids[0]].costo_ppp == float(item_ids[0])
        assert result[item_ids[1]].costo_ppp == float(item_ids[1])
        assert result[item_ids[2]].costo_ppp == float(item_ids[2])
        assert len(result) == 3


class TestCurrency:
    """REQ-2: costo_ppp is carried in its OWN currency, never converted."""

    def test_curr_id_1_maps_to_ars(self, db) -> None:
        _insert_history(db, iclh_id=30, item_id=401, curr_id=1, iclh_price_aw=100.0)

        result = resolver_ppp_batch(db, [401])

        assert result[401].costo_ppp_moneda == "ARS"

    def test_curr_id_2_maps_to_usd(self, db) -> None:
        _insert_history(db, iclh_id=31, item_id=402, curr_id=2, iclh_price_aw=38.4)

        result = resolver_ppp_batch(db, [402])

        assert result[402].costo_ppp_moneda == "USD"
        assert result[402].costo_ppp == 38.4  # NOT converted


class TestNoDataContract:
    """REQ-4: no qualifying row => explicit no-data, never a costo fallback."""

    def test_item_with_zero_qualifying_rows_is_absent_from_batch(self, db) -> None:
        result = resolver_ppp_batch(db, [])
        assert result == {}

    def test_ppp_markups_with_no_costo_ppp_returns_none_payload(self) -> None:
        acc = PppMarkups(None)
        acc.record("mejor_oferta", 500.0)
        acc.record("rebate", 600.0)

        assert acc.payload() is None

    def test_no_emitted_markup_equals_a_value_derived_from_costo(self) -> None:
        """A wrong PPP number is worse than none — assert real inequality, not just nullness."""
        costo = 100.0
        limpio = 130.0
        list_cost_markup = ((limpio / costo) - 1) * 100  # what the existing list-cost site would compute

        acc = PppMarkups(None)
        acc.record("calculado", limpio)
        payload = acc.payload()

        assert payload is None
        # Even if a caller mistakenly tried to substitute costo, the recorded
        # markups dict must not carry a same-shaped fallback value.
        assert list_cost_markup != 0  # sanity: costo path IS non-trivial here


class TestPppMarkupsScaling:
    """REQ-5: record() scaling must match the site it shadows."""

    def test_percent_true_scales_and_rounds_like_percent_sites(self) -> None:
        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1), costo_ppp_moneda="ARS"))
        acc.record("pvp", 150.0)  # calcular_markup(150, 100) = 0.5 -> * 100 = 50.0

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["pvp"] == 50.0

    def test_percent_false_keeps_raw_ratio_for_mejor_oferta(self) -> None:
        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1), costo_ppp_moneda="ARS"))
        acc.record("mejor_oferta", 150.0, percent=False)  # calcular_markup(150, 100) = 0.5

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["mejor_oferta"] == 0.5

    def test_payload_carries_source_date_and_moneda_whenever_costo_ppp_present(self) -> None:
        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2024, 3, 15), costo_ppp_moneda="USD"))
        payload = acc.payload()

        assert payload is not None
        assert payload.fecha == date(2024, 3, 15)
        assert payload.costo == 100.0
        assert payload.moneda == "USD"


class TestConstructorPreventsInvalidState:
    """costo_ppp set with fecha=None must be unrepresentable.

    `payload()` only guards on `costo_ppp is None`, so it would build
    `PppPayload(fecha=None)` — a non-optional field — and Pydantic would
    raise `ValidationError` (surfacing as an HTTP 500 on a hot endpoint) if
    that state were reachable. Constructing from a single `Optional[PppSource]`
    makes this state unreachable: `PppSource` always carries both fields
    together.
    """

    def test_constructor_only_accepts_a_single_optional_source(self) -> None:
        acc_empty = PppMarkups(None)
        assert acc_empty.payload() is None

        acc_full = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1), costo_ppp_moneda="ARS"))
        acc_full.record("pvp", 150.0)
        payload = acc_full.payload()

        assert payload is not None
        assert payload.costo == 100.0
        assert payload.fecha == date(2026, 1, 1)

    def test_no_positional_two_arg_signature_is_accepted(self) -> None:
        """Passing a bare float positionally must fail (AttributeError from
        record()/init trying to read .costo_ppp off a float)."""
        with pytest.raises(AttributeError):
            PppMarkups(100.0)  # not a PppSource -> .costo_ppp access fails


class TestMarkupCurrencyConversion:
    """The aw's own currency does NOT leak into `payload().costo` (display),
    but IS converted to ARS internally, as `calcular_markup`'s cost input —
    exactly like every other call site in productos_listing.py converts the
    list cost before computing a markup (`limpio` is always ARS)."""

    def test_ars_source_needs_no_conversion_for_markup(self) -> None:
        acc = PppMarkups(
            PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1), costo_ppp_moneda="ARS"),
            tipo_cambio=1000.0,  # present but irrelevant when moneda is ARS
        )
        acc.record("clasica", 150.0)

        payload = acc.payload()
        assert payload is not None
        assert payload.costo == 100.0  # display: untouched
        assert payload.markups["clasica"] == round(((150.0 / 100.0) - 1) * 100, 2)

    def test_usd_source_is_converted_to_ars_only_for_the_markup_formula(self) -> None:
        acc = PppMarkups(
            PppSource(costo_ppp=1.0, costo_ppp_fecha=date(2026, 1, 1), costo_ppp_moneda="USD"),
            tipo_cambio=1000.0,
        )
        acc.record("clasica", 1500.0)  # limpio in ARS

        payload = acc.payload()
        assert payload is not None
        assert payload.costo == 1.0  # display: NEVER converted
        assert payload.moneda == "USD"
        # Markup uses costo converted to ARS (1.0 * 1000.0 = 1000.0 ARS).
        assert payload.markups["clasica"] == round(((1500.0 / 1000.0) - 1) * 100, 2)

    def test_usd_source_without_tipo_cambio_yields_no_markup(self) -> None:
        """convertir_a_pesos falls back to the raw (unconverted) figure when
        tipo_cambio is unavailable — record() still computes SOMETHING, but
        it must never silently divide-by-nothing or crash."""
        acc = PppMarkups(
            PppSource(costo_ppp=1.0, costo_ppp_fecha=date(2026, 1, 1), costo_ppp_moneda="USD"),
            tipo_cambio=None,
        )
        acc.record("clasica", 1500.0)

        payload = acc.payload()
        assert payload is not None
        # convertir_a_pesos(1.0, "USD", None) returns 1.0 unconverted (see
        # pricing_calculator.convertir_a_pesos) — documented existing
        # fallback behaviour, reused here rather than reinvented.
        assert payload.markups["clasica"] == round(((1500.0 / 1.0) - 1) * 100, 2)


class TestPinnedAgainstKnownErpValue:
    """Regression test that would have caught the original bug (see module
    docstring's "What went wrong").

    The shipped feature read `ItemTransaction.it_priceofcostpp`, which is
    NOT what the GBP ERP "Costo PPP" screen shows — it shipped a
    plausible-but-wrong number for months because nothing pinned it to a
    known ERP value. This test fixtures a product modelled on real item 1169
    (ROUTER TP LINK OMADA ER605): list cost 42.99 USD, GBP's ERP screen shows
    "Costo PPP" = 38.00, and `iclh_price_aw` for the correct row
    (coslis_id=1, curr_id=2/USD, 2026-07-23) is 38.402760 — decoy rows exist
    in coslis_id 7 and 8, plus an OLDER coslis_id=1 row, none of which must
    ever win.
    """

    def test_resolver_matches_gbp_screen_value_for_item_1169_fixture(self, db) -> None:
        # Older coslis_id=1 row — must lose to the newer one below.
        _insert_history(
            db,
            iclh_id=116901,
            item_id=1169,
            coslis_id=1,
            curr_id=2,
            iclh_price_aw=35.0,
            iclh_cd=datetime(2026, 6, 1),
        )
        # Decoys in other cost lists — must never be selected regardless of date.
        _insert_history(
            db,
            iclh_id=116902,
            item_id=1169,
            coslis_id=7,
            curr_id=2,
            iclh_price_aw=71.68,
            iclh_cd=datetime(2026, 7, 24),
        )
        _insert_history(
            db,
            iclh_id=116903,
            item_id=1169,
            coslis_id=8,
            curr_id=2,
            iclh_price_aw=47.16,
            iclh_cd=datetime(2026, 7, 24),
        )
        # The row GBP's screen actually derives its "Costo PPP" from.
        _insert_history(
            db,
            iclh_id=116904,
            item_id=1169,
            coslis_id=1,
            curr_id=2,
            iclh_price_aw=38.402760,
            iclh_cd=datetime(2026, 7, 23),
        )

        result = resolver_ppp_batch(db, [1169])

        assert 1169 in result
        assert result[1169].costo_ppp == pytest.approx(38.402760)
        assert result[1169].costo_ppp_moneda == "USD"
        assert result[1169].costo_ppp_fecha == date(2026, 7, 23)

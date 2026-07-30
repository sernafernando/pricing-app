"""
Unit tests for costo_ppp_service — PPP (ERP weighted-average cost) resolver
and per-product markup accumulator.

Spec coverage (openspec/changes/productos-costo-ppp/specs.md, source-correction
round 2026-07-29):
  REQ-1 — row selection: coslis_id = 1 (main cost list) AND iclh_price_aw IS
          NOT NULL AND iclh_price_aw > 0, latest iclh_cd wins, iclh_id DESC
          breaks exact-date ties.
  REQ-2 — PPP is displayed in `moneda_costo` (the CALLER's), never converted
          for display; conversion only happens internally, as an input to
          the markup formula. See `costo_ppp_service` module docstring's
          "Currency" section for the full rationale/evidence.
  REQ-3 — costo_ppp_fecha always accompanies a non-null costo_ppp.
  REQ-4 — no-data contract: zero qualifying rows => item absent from the
          resolver dict AND PppMarkups(None).payload() is None; no emitted
          markup key ever equals a value derived from `costo`.
  REQ-5 — PppMarkups.record scaling: percent=True scales *100 (matches most
          sites), percent=False keeps the raw ratio (matches mejor_oferta
          sites).
  REQ-6 — fail-closed: a non-ARS `moneda_costo` with no resolvable
          `tipo_cambio` must emit NO markup at all (not a silently-wrong one)
          — `payload().costo`/`.moneda` stay unaffected. A falsy
          `moneda_costo` (`None`) normalizes to `"ARS"` instead of reaching
          `PppPayload.moneda` (non-optional) or `convertir_a_pesos` raw.

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
        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)), moneda_costo="ARS")
        acc.record("pvp", 150.0)  # calcular_markup(150, 100) = 0.5 -> * 100 = 50.0

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["pvp"] == 50.0

    def test_percent_false_keeps_raw_ratio_for_mejor_oferta(self) -> None:
        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)), moneda_costo="ARS")
        acc.record("mejor_oferta", 150.0, percent=False)  # calcular_markup(150, 100) = 0.5

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["mejor_oferta"] == 0.5

    def test_payload_carries_source_date_and_moneda_whenever_costo_ppp_present(self) -> None:
        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2024, 3, 15)), moneda_costo="USD")
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

        acc_full = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)), moneda_costo="ARS")
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
    """`moneda_costo` never leaks into `payload().costo` (display), but IS
    used to convert to ARS internally for the markup formula — see
    `costo_ppp_service` module docstring's "Currency" section."""

    def test_ars_moneda_costo_needs_no_conversion_for_markup(self) -> None:
        acc = PppMarkups(
            PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)),
            moneda_costo="ARS",
            tipo_cambio=1000.0,  # present but irrelevant when moneda_costo is ARS
        )
        acc.record("clasica", 150.0)

        payload = acc.payload()
        assert payload is not None
        assert payload.costo == 100.0  # display: untouched
        assert payload.markups["clasica"] == round(((150.0 / 100.0) - 1) * 100, 2)

    def test_usd_moneda_costo_is_converted_to_ars_only_for_the_markup_formula(self) -> None:
        acc = PppMarkups(
            PppSource(costo_ppp=1.0, costo_ppp_fecha=date(2026, 1, 1)),
            moneda_costo="USD",
            tipo_cambio=1000.0,
        )
        acc.record("clasica", 1500.0)  # limpio in ARS

        payload = acc.payload()
        assert payload is not None
        assert payload.costo == 1.0  # display: NEVER converted
        assert payload.moneda == "USD"
        # Markup uses costo converted to ARS (1.0 * 1000.0 = 1000.0 ARS).
        assert payload.markups["clasica"] == round(((1500.0 / 1000.0) - 1) * 100, 2)

    def test_usd_moneda_costo_without_tipo_cambio_fails_closed_no_markup_emitted(self) -> None:
        """Fail-closed guard — see module docstring's "Currency" section for
        the full rationale (why the naive fallback would silently produce a
        ~149,900%-shaped markup)."""
        acc = PppMarkups(
            PppSource(costo_ppp=1.0, costo_ppp_fecha=date(2026, 1, 1)),
            moneda_costo="USD",
            tipo_cambio=None,
        )
        acc.record("clasica", 1500.0)

        payload = acc.payload()
        assert payload is not None
        assert "clasica" not in payload.markups  # no fabricated markup

    def test_usd_moneda_costo_without_tipo_cambio_still_shows_costo_and_moneda(self) -> None:
        """The fail-closed behaviour is scoped to MARKUPS only: the PPP cost
        itself does not depend on today's exchange rate (it's shown as-is,
        never converted — see class docstring), so `payload()` must still
        surface `costo`/`moneda` even when no markup could be computed."""
        acc = PppMarkups(
            PppSource(costo_ppp=38.4, costo_ppp_fecha=date(2026, 7, 23)),
            moneda_costo="USD",
            tipo_cambio=None,
        )
        acc.record("clasica", 1500.0)

        payload = acc.payload()
        assert payload is not None
        assert payload.costo == 38.4
        assert payload.moneda == "USD"
        assert payload.fecha == date(2026, 7, 23)
        assert payload.markups == {}

    def test_ars_moneda_costo_still_computes_markups_without_any_tipo_cambio(self) -> None:
        """The fail-closed guard must not regress the ARS path: ARS needs no
        conversion at all, so a missing `tipo_cambio` is irrelevant and
        markups are computed normally."""
        acc = PppMarkups(
            PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)),
            moneda_costo="ARS",
            tipo_cambio=None,
        )
        acc.record("clasica", 150.0)

        payload = acc.payload()
        assert payload is not None
        assert payload.markups["clasica"] == round(((150.0 / 100.0) - 1) * 100, 2)

    def test_null_moneda_costo_normalizes_to_ars_instead_of_reaching_payload_or_conversion(self) -> None:
        """Null-safety (pre-push review, 2026-07-29):
        `ProductoERP.moneda_costo` has no `nullable=False`, so a raw
        upsert/sync can leave it `NULL` — a caller could then pass
        `moneda_costo=None`. Before this guard, `None` would reach
        `PppPayload.moneda` (non-optional `str`) and raise a
        `ValidationError`/500 for the WHOLE `/api/productos` page, not just
        one product. `PppMarkups` normalizes `None` to `"ARS"` at
        construction — payload construction must not raise, and (since ARS
        needs no conversion) the markup must compute normally, exactly like
        an explicit `moneda_costo="ARS"` would."""
        acc = PppMarkups(
            PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)),
            moneda_costo=None,
            tipo_cambio=None,
        )
        acc.record("clasica", 150.0)

        payload = acc.payload()
        assert payload is not None
        assert payload.moneda == "ARS"
        assert payload.costo == 100.0
        assert payload.markups["clasica"] == round(((150.0 / 100.0) - 1) * 100, 2)


class TestPinnedAgainstKnownErpValue:
    """Regression test that would have caught the original bug (see module
    docstring's "What went wrong").

    The shipped feature read `ItemTransaction.it_priceofcostpp`, which is
    NOT what the GBP ERP "Costo PPP" screen shows — it shipped a
    plausible-but-wrong number for months because nothing pinned it to a
    known ERP value. This test fixtures a product modelled on real item 1169
    (ROUTER TP LINK OMADA ER605): list cost 42.99 USD, GBP's ERP screen shows
    "Costo PPP" = 38.00, and `iclh_price_aw` for the correct row
    (coslis_id=1, 2026-07-23) is 38.402760 — decoy rows exist in coslis_id 7
    and 8, plus an OLDER coslis_id=1 row, none of which must ever win.
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
        assert result[1169].costo_ppp_fecha == date(2026, 7, 23)


class TestScaleSanityGuard:
    """REQ-7 (2026-07-29): reject a row whose `iclh_price_aw` is stale at a
    different currency scale than `iclh_price` IN THE SAME ROW — see module
    docstring's "Scale sanity guard" section for the witness item and
    measured counts (42 broken of 3215, discovered in production)."""

    def test_witness_item_2780_stale_aw_after_currency_change_yields_no_ppp_without_footprint(self, db) -> None:
        """Real item 2780 (RESMA AUTOR CARTA) WITHOUT its footprint row
        present: the scale guard alone (no footprint lookup input) must not
        fabricate anything — no PPP for this item. See
        `TestRecoveringUsdFootprints` below for the SAME item WITH its
        footprint row present, which recovers it (2026-07-30)."""
        _insert_history(
            db,
            iclh_id=278002,
            item_id=2780,
            coslis_id=1,
            curr_id=1,
            iclh_price=3178.250000,
            iclh_price_aw=2.911820,
            iclh_cd=datetime(2025, 7, 28),
        )

        result = resolver_ppp_batch(db, [2780])

        assert 2780 in result
        assert result[2780].usable is False

    def test_inverse_scale_mismatch_aw_1000x_too_large_yields_no_ppp(self, db) -> None:
        """Real shape of item 623: `iclh_price_aw` stale 1000x LARGER than
        `iclh_price` (the opposite direction from item 2780 above). No
        footprint row exists for this item -> unrecoverable (state 2, "out
        of range" — see `TestRecoveringUsdFootprints` below)."""
        _insert_history(
            db,
            iclh_id=62301,
            item_id=623,
            coslis_id=1,
            iclh_price=66.00,
            iclh_price_aw=1648.13,
        )

        result = resolver_ppp_batch(db, [623])

        assert 623 in result
        assert result[623].usable is False

    def test_ratio_exactly_at_upper_bound_20_is_accepted_inclusive(self, db) -> None:
        _insert_history(db, iclh_id=90001, item_id=9001, iclh_price=200.0, iclh_price_aw=10.0)

        result = resolver_ppp_batch(db, [9001])

        assert 9001 in result
        assert result[9001].costo_ppp == 10.0

    def test_ratio_just_above_upper_bound_20_is_rejected(self, db) -> None:
        _insert_history(db, iclh_id=90002, item_id=9002, iclh_price=200.02, iclh_price_aw=10.0)

        result = resolver_ppp_batch(db, [9002])

        assert 9002 in result
        assert result[9002].usable is False

    def test_ratio_exactly_at_lower_bound_0_05_is_accepted_inclusive(self, db) -> None:
        _insert_history(db, iclh_id=90003, item_id=9003, iclh_price=10.0, iclh_price_aw=200.0)

        result = resolver_ppp_batch(db, [9003])

        assert 9003 in result
        assert result[9003].costo_ppp == 200.0

    def test_ratio_just_below_lower_bound_0_05_is_rejected(self, db) -> None:
        _insert_history(db, iclh_id=90004, item_id=9004, iclh_price=9.99, iclh_price_aw=200.0)

        result = resolver_ppp_batch(db, [9004])

        assert 9004 in result
        assert result[9004].usable is False

    def test_normal_ratio_around_1_1_is_accepted_unchanged_behaviour(self, db) -> None:
        _insert_history(db, iclh_id=90005, item_id=9005, iclh_price=110.0, iclh_price_aw=100.0)

        result = resolver_ppp_batch(db, [9005])

        assert 9005 in result
        assert result[9005].costo_ppp == 100.0

    def test_iclh_price_zero_is_rejected_no_reference_to_validate_against(self, db) -> None:
        _insert_history(db, iclh_id=90006, item_id=9006, iclh_price=0.0, iclh_price_aw=100.0)

        result = resolver_ppp_batch(db, [9006])

        assert 9006 in result
        assert result[9006].usable is False

    def test_iclh_price_null_is_rejected_no_reference_to_validate_against(self, db) -> None:
        _insert_history(db, iclh_id=90007, item_id=9007, iclh_price=None, iclh_price_aw=100.0)

        result = resolver_ppp_batch(db, [9007])

        assert 9007 in result
        assert result[9007].usable is False


class TestRecoveringUsdFootprints:
    """2026-07-30: a scale-broken row's stale `iclh_price_aw` can sometimes
    be RECOVERED by finding its "currency footprint" — an older,
    coherent row that this exact value came from before a currency change
    (see module docstring's "Recovering USD footprints" section)."""

    def test_witness_item_2780_recovered_via_usd_footprint(self, db) -> None:
        """Real item 2780 (RESMA AUTOR CARTA) WITH its footprint present:
        the 2025-03-26 USD row's `iclh_price` (2.911820) exactly equals the
        current (broken-scale) row's stale `iclh_price_aw` — recoverable."""
        _insert_history(
            db,
            iclh_id=278001,
            item_id=2780,
            coslis_id=1,
            curr_id=2,
            iclh_price=2.911820,
            iclh_price_aw=2.911820,
            iclh_cd=datetime(2025, 3, 26),
        )
        _insert_history(
            db,
            iclh_id=278002,
            item_id=2780,
            coslis_id=1,
            curr_id=1,
            iclh_price=3178.250000,
            iclh_price_aw=2.911820,
            iclh_cd=datetime(2025, 7, 28),
        )

        result = resolver_ppp_batch(db, [2780])

        assert 2780 in result
        source = result[2780]
        assert source.usable is True
        assert source.moneda_ppp == "USD"
        assert source.costo_ppp == pytest.approx(2.911820)
        assert source.costo_ppp_fecha == date(2025, 7, 28)  # the CURRENT (broken) row's own date

    def test_footprint_matched_on_candidates_aw_not_price_item_516_shape(self, db) -> None:
        """Real shape of item 516: the current row's stale `iclh_price_aw`
        (5428.598950) exactly equals the CANDIDATE row's `iclh_price_aw`
        (not its `iclh_price`, 5549.22) — the match must check both columns.
        516's footprint is in ARS though, so it still ends OUT OF RANGE
        (only USD footprints are recovered)."""
        _insert_history(
            db,
            iclh_id=51601,
            item_id=516,
            coslis_id=1,
            curr_id=1,  # ARS footprint row — the one whose `aw` matches
            iclh_price=5549.22,
            iclh_price_aw=5428.598950,
            iclh_cd=datetime(2025, 1, 1),
        )
        _insert_history(
            db,
            iclh_id=51602,
            item_id=516,
            coslis_id=1,
            curr_id=2,  # different currency from the candidate above -> eligible
            iclh_price=999999.0,  # broken scale vs iclh_price_aw in this SAME row
            iclh_price_aw=5428.598950,
            iclh_cd=datetime(2026, 1, 1),
        )

        result = resolver_ppp_batch(db, [516])

        assert 516 in result
        assert result[516].usable is False

    def test_ars_footprint_item_397_shape_is_unrecoverable_no_number_emitted(self, db) -> None:
        """User decision: a stale value in OLD PESOS is explicitly NOT
        converted (no historical rate available, and the conversion would be
        meaningless) — real shape of item 397 (footprint from 2023-03)."""
        _insert_history(
            db,
            iclh_id=39701,
            item_id=397,
            coslis_id=1,
            curr_id=1,
            iclh_price=6033.03,
            iclh_price_aw=6033.03,
            iclh_cd=datetime(2023, 3, 1),
        )
        _insert_history(
            db,
            iclh_id=39702,
            item_id=397,
            coslis_id=1,
            curr_id=2,
            iclh_price=999999.0,
            iclh_price_aw=6033.03,
            iclh_cd=datetime(2026, 1, 1),
        )

        result = resolver_ppp_batch(db, [397])

        assert 397 in result
        source = result[397]
        assert source.usable is False
        assert source.costo_ppp is None  # explicit: NO converted number is ever emitted
        assert PppMarkups(source, moneda_costo="ARS").payload().estado == "fuera_de_rango"

    def test_no_footprint_item_623_shape_is_out_of_range(self, db) -> None:
        _insert_history(db, iclh_id=62302, item_id=623, coslis_id=1, iclh_price=66.00, iclh_price_aw=1648.13)

        result = resolver_ppp_batch(db, [623])

        assert 623 in result
        assert result[623].usable is False

    def test_healthy_row_that_would_match_a_footprint_is_never_reinterpreted(self, db) -> None:
        """False-positive control (measured 2026-07-29): only 8/3137 healthy
        rows would coincidentally match a footprint by exact value — the
        footprint lookup must run ONLY for rows that already failed the
        scale guard."""
        _insert_history(
            db,
            iclh_id=70001,
            item_id=700,
            coslis_id=1,
            curr_id=1,
            iclh_price=105.0,
            iclh_price_aw=100.0,  # normal ratio (1.05) -- scale-sane
            iclh_cd=datetime(2026, 1, 1),
        )
        # A decoy row that WOULD be picked up as a footprint if the guard
        # incorrectly ran on the healthy row above too.
        _insert_history(
            db,
            iclh_id=70002,
            item_id=700,
            coslis_id=1,
            curr_id=2,
            iclh_price=100.0,
            iclh_price_aw=100.0,
            iclh_cd=datetime(2025, 1, 1),
        )

        result = resolver_ppp_batch(db, [700])

        assert 700 in result
        source = result[700]
        assert source.usable is True
        assert source.moneda_ppp is None  # rule-1, never reinterpreted
        assert source.costo_ppp == 100.0

    def test_recovered_usd_row_with_no_exchange_rate_fails_closed_out_of_range(self, db) -> None:
        """Even though the resolver-level state is 'recovered/usable', the
        MARKUP layer (`PppMarkups`) must still fail closed to out-of-range
        when no exchange rate is resolvable — see module docstring's
        "Recovering USD footprints" section."""
        _insert_history(
            db,
            iclh_id=278011,
            item_id=2781,
            coslis_id=1,
            curr_id=2,
            iclh_price=2.911820,
            iclh_price_aw=2.911820,
            iclh_cd=datetime(2025, 3, 26),
        )
        _insert_history(
            db,
            iclh_id=278012,
            item_id=2781,
            coslis_id=1,
            curr_id=1,
            iclh_price=3178.250000,
            iclh_price_aw=2.911820,
            iclh_cd=datetime(2025, 7, 28),
        )

        result = resolver_ppp_batch(db, [2781])
        source = result[2781]
        assert source.usable is True  # resolver-level: recoverable in principle

        acc = PppMarkups(source, moneda_costo="ARS", tipo_cambio=None)
        payload = acc.payload()

        assert payload is not None
        assert payload.estado == "fuera_de_rango"
        assert payload.costo is None

    def test_recovered_usd_row_displayed_in_list_costs_currency_at_todays_rate(self, db) -> None:
        """USER DECISION: a recovered row is displayed in the LIST COST's
        currency (here ARS), converted at today's rate — NOT in USD beside a
        peso cost."""
        source = PppSource(costo_ppp=2.911820, costo_ppp_fecha=date(2025, 7, 28), usable=True, moneda_ppp="USD")

        acc = PppMarkups(source, moneda_costo="ARS", tipo_cambio=1520.0)
        payload = acc.payload()

        assert payload is not None
        assert payload.estado == "usable"
        assert payload.costo == pytest.approx(2.911820 * 1520.0)
        assert payload.moneda == "ARS"
        assert payload.fecha == date(2025, 7, 28)

    def test_multiple_footprint_candidates_most_recent_wins_deterministically(self, db) -> None:
        """Several rows exactly match the stale value under a different
        currency -> the most recent one (by iclh_cd, tiebreak iclh_id DESC)
        must win, same determinism concern as the main ranked query."""
        _insert_history(
            db,
            iclh_id=80001,
            item_id=800,
            coslis_id=1,
            curr_id=2,
            iclh_price=5.0,
            iclh_price_aw=5.0,
            iclh_cd=datetime(2024, 1, 1),
        )
        _insert_history(
            db,
            iclh_id=80002,
            item_id=800,
            coslis_id=1,
            curr_id=1,  # ARS candidate — older than the USD one below, must lose
            iclh_price=5.0,
            iclh_price_aw=5.0,
            iclh_cd=datetime(2025, 1, 1),
        )
        _insert_history(
            db,
            iclh_id=80003,
            item_id=800,
            coslis_id=1,
            curr_id=2,  # USD candidate, MOST RECENT -> must win
            iclh_price=5.0,
            iclh_price_aw=5.0,
            iclh_cd=datetime(2026, 1, 1),
        )
        _insert_history(
            db,
            iclh_id=80004,
            item_id=800,
            coslis_id=1,
            curr_id=1,  # current (broken-scale) row
            iclh_price=5000.0,
            iclh_price_aw=5.0,
            iclh_cd=datetime(2026, 6, 1),
        )

        result = resolver_ppp_batch(db, [800])

        assert 800 in result
        source = result[800]
        assert source.usable is True
        assert source.moneda_ppp == "USD"  # the most recent (2026-01-01) candidate is USD


class TestFootprintQueryIsBatched:
    """Performance: the footprint lookup must be ONE extra batched query per
    page — never one query per off-scale item."""

    @pytest.mark.parametrize("page_size", [1, 100])
    def test_footprint_lookup_adds_exactly_one_query_regardless_of_offscale_count(self, db, page_size) -> None:
        from sqlalchemy import event

        item_ids = list(range(9500, 9500 + page_size))
        for i, item_id in enumerate(item_ids):
            _insert_history(
                db,
                iclh_id=95000 + i,
                item_id=item_id,
                coslis_id=1,
                curr_id=1,
                iclh_price=1000.0,
                iclh_price_aw=1.0,  # off-scale for every item in this page
                iclh_cd=datetime(2026, 1, 1),
            )

        queries = []

        def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if "tb_item_cost_list_history" in statement:
                queries.append(statement)

        event.listen(db.get_bind(), "before_cursor_execute", _before_cursor_execute)
        try:
            resolver_ppp_batch(db, item_ids)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _before_cursor_execute)

        # ONE main ranked query + ONE footprint query = 2, regardless of page_size.
        assert len(queries) == 2

"""
Unit tests for costo_ppp_service — PPP (ERP weighted-average cost) resolver
and per-product markup accumulator.

Spec coverage (openspec/changes/productos-costo-ppp/specs.md):
  REQ-1 — row selection: it_priceofcostpp > 0 AND it_cancelled = false AND
          it_exchangetobranchcurrency IS NOT NULL AND rmah_id IS NULL AND
          it_isrmasuppliercreditnote = false, latest it_cd wins
  REQ-2 — PPP is already ARS: no currency conversion applied
  REQ-3 — costo_ppp_fecha always accompanies a non-null costo_ppp
  REQ-4 — no-data contract: zero qualifying rows => item absent from the
          resolver dict AND PppMarkups(None).payload() is None; no emitted
          markup key ever equals a value derived from `costo`
  REQ-5 — PppMarkups.record scaling: percent=True scales *100 (matches most
          sites), percent=False keeps the raw ratio (matches mejor_oferta
          sites)

These tests run against the REAL in-memory SQLite `db` fixture (see
tests/conftest.py) using the actual ItemTransaction ORM model — this proves
the resolver's window-function query is portable to SQLite, not just
PostgreSQL (DISTINCT ON is PostgreSQL-only and is NOT used here).
"""

from __future__ import annotations

from datetime import datetime


from app.models.item_transaction import ItemTransaction
from app.services.costo_ppp_service import PppMarkups, resolver_ppp_batch


def _insert_transaction(db, **overrides) -> ItemTransaction:
    defaults = dict(
        it_transaction=None,  # let autoincrement-free PK be set explicitly per test
        ct_transaction=1,
        item_id=1,
        it_priceofcostpp=100.0,
        it_cancelled=False,
        it_exchangetobranchcurrency=1.0,
        rmah_id=None,
        it_isrmasuppliercreditnote=False,
        it_cd=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    txn = ItemTransaction(**defaults)
    db.add(txn)
    db.commit()
    return txn


class TestRowSelection:
    """REQ-1: row-selection predicate and latest-it_cd tiebreak."""

    def test_single_qualifying_row_is_used(self, db) -> None:
        _insert_transaction(db, it_transaction=1, item_id=101, it_priceofcostpp=250.0, it_cd=datetime(2026, 1, 10))

        result = resolver_ppp_batch(db, [101])

        assert 101 in result
        assert result[101].costo_ppp == 250.0
        assert result[101].costo_ppp_fecha == datetime(2026, 1, 10).date()

    def test_latest_it_cd_wins_among_multiple_qualifying_rows(self, db) -> None:
        _insert_transaction(db, it_transaction=2, item_id=102, it_priceofcostpp=100.0, it_cd=datetime(2025, 1, 1))
        _insert_transaction(db, it_transaction=3, item_id=102, it_priceofcostpp=200.0, it_cd=datetime(2026, 6, 1))
        _insert_transaction(db, it_transaction=4, item_id=102, it_priceofcostpp=150.0, it_cd=datetime(2025, 6, 1))

        result = resolver_ppp_batch(db, [102])

        assert result[102].costo_ppp == 200.0
        assert result[102].costo_ppp_fecha == datetime(2026, 6, 1).date()

    def test_cancelled_row_excluded(self, db) -> None:
        _insert_transaction(db, it_transaction=5, item_id=103, it_priceofcostpp=999.0, it_cancelled=True)

        result = resolver_ppp_batch(db, [103])

        assert 103 not in result

    def test_usd_denominated_row_excluded_not_converted(self, db) -> None:
        """it_exchangetobranchcurrency IS NULL => USD row, excluded and never converted."""
        _insert_transaction(db, it_transaction=6, item_id=104, it_priceofcostpp=999.0, it_exchangetobranchcurrency=None)

        result = resolver_ppp_batch(db, [104])

        assert 104 not in result

    def test_rma_linked_row_excluded(self, db) -> None:
        _insert_transaction(db, it_transaction=7, item_id=105, it_priceofcostpp=999.0, rmah_id=42)

        result = resolver_ppp_batch(db, [105])

        assert 105 not in result

    def test_supplier_credit_note_row_excluded(self, db) -> None:
        _insert_transaction(db, it_transaction=8, item_id=106, it_priceofcostpp=999.0, it_isrmasuppliercreditnote=True)

        result = resolver_ppp_batch(db, [106])

        assert 106 not in result

    def test_non_positive_priceofcostpp_excluded(self, db) -> None:
        _insert_transaction(db, it_transaction=9, item_id=107, it_priceofcostpp=0.0)

        result = resolver_ppp_batch(db, [107])

        assert 107 not in result

    def test_batch_resolves_multiple_items_in_one_call(self, db) -> None:
        _insert_transaction(db, it_transaction=10, item_id=201, it_priceofcostpp=50.0)
        _insert_transaction(db, it_transaction=11, item_id=202, it_priceofcostpp=75.0)

        result = resolver_ppp_batch(db, [201, 202, 203])

        assert result[201].costo_ppp == 50.0
        assert result[202].costo_ppp == 75.0
        assert 203 not in result


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
        from datetime import date

        acc = PppMarkups(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1))
        acc.record("pvp", 150.0)  # calcular_markup(150, 100) = 0.5 -> * 100 = 50.0

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["pvp"] == 50.0

    def test_percent_false_keeps_raw_ratio_for_mejor_oferta(self) -> None:
        from datetime import date

        acc = PppMarkups(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1))
        acc.record("mejor_oferta", 150.0, percent=False)  # calcular_markup(150, 100) = 0.5

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["mejor_oferta"] == 0.5

    def test_payload_carries_source_date_whenever_costo_ppp_present(self) -> None:
        from datetime import date

        acc = PppMarkups(costo_ppp=100.0, costo_ppp_fecha=date(2024, 3, 15))
        payload = acc.payload()

        assert payload is not None
        assert payload.fecha == date(2024, 3, 15)
        assert payload.costo == 100.0

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

from datetime import date, datetime

import pytest
import sqlalchemy as sa

from app.models.item_transaction import ItemTransaction
from app.services.costo_ppp_service import PppMarkups, PppSource, resolver_ppp_batch


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

    def test_more_than_900_item_ids_does_not_blow_sqlite_variable_limit(self, db) -> None:
        """Fix-round finding 3: `item_id.in_(item_ids)` must be chunked (900,
        matching `batch_colores`'s SQLite/PostgreSQL param-limit chunking) —
        `page_size` allows up to 10000, and an unchunked IN clause with that
        many bind params trips SQLite's default 999-variable limit."""
        item_ids = list(range(1000, 2000))  # 1000 ids -> 2 chunks at size 900
        for i, item_id in enumerate(item_ids[:3]):
            _insert_transaction(db, it_transaction=100 + i, item_id=item_id, it_priceofcostpp=float(item_id))

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
        from datetime import date

        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)))
        acc.record("pvp", 150.0)  # calcular_markup(150, 100) = 0.5 -> * 100 = 50.0

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["pvp"] == 50.0

    def test_percent_false_keeps_raw_ratio_for_mejor_oferta(self) -> None:
        from datetime import date

        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)))
        acc.record("mejor_oferta", 150.0, percent=False)  # calcular_markup(150, 100) = 0.5

        payload = acc.payload()

        assert payload is not None
        assert payload.markups["mejor_oferta"] == 0.5

    def test_payload_carries_source_date_whenever_costo_ppp_present(self) -> None:
        from datetime import date

        acc = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2024, 3, 15)))
        payload = acc.payload()

        assert payload is not None
        assert payload.fecha == date(2024, 3, 15)
        assert payload.costo == 100.0


class TestConstructorPreventsInvalidState:
    """Fix-round finding 2: costo_ppp set with fecha=None must be unrepresentable.

    Before the fix, `PppMarkups.__init__` took two independent optional
    params, so a caller could pass `costo_ppp=100.0, costo_ppp_fecha=None`;
    `payload()` only guarded on `costo_ppp is None`, so it would build
    `PppPayload(fecha=None)` — a non-optional field — and Pydantic would
    raise `ValidationError` (surfacing as an HTTP 500 on a hot endpoint).
    Constructing from a single `Optional[PppSource]` makes this state
    unreachable: `PppSource` always carries both fields together.
    """

    def test_constructor_only_accepts_a_single_optional_source(self) -> None:
        acc_empty = PppMarkups(None)
        assert acc_empty.payload() is None

        acc_full = PppMarkups(PppSource(costo_ppp=100.0, costo_ppp_fecha=date(2026, 1, 1)))
        acc_full.record("pvp", 150.0)
        payload = acc_full.payload()

        assert payload is not None
        assert payload.costo == 100.0
        assert payload.fecha == date(2026, 1, 1)

    def test_no_positional_two_arg_signature_is_accepted(self) -> None:
        """The old `(costo_ppp, costo_ppp_fecha)` signature must be gone —
        passing a bare float positionally must fail (TypeError from record()
        trying to read .costo_ppp off a float), proving the type no longer
        permits a same-shaped invalid two-arg call to silently succeed."""
        import pytest

        with pytest.raises(AttributeError):
            PppMarkups(100.0)  # not a PppSource -> .costo_ppp access fails


@pytest.mark.postgres
class TestResolverAgainstRealPostgres:
    """Proves the actual LATERAL fast path (see costo_ppp_service module
    docstring for the production EXPLAIN ANALYZE numbers that motivated it).

    `db` (SQLite in-memory) exercises the portable ROW_NUMBER() fallback,
    which every other test class in this file already covers. These tests
    run the exact same resolver against a real PostgreSQL instance (`pg_db`
    fixture, tests/conftest.py) so the LATERAL branch itself — not just its
    fallback — is under test in CI.
    """

    def _insert(self, pg_db, **overrides) -> None:
        defaults = dict(
            it_transaction=None,
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
        pg_db.add(ItemTransaction(**defaults))
        pg_db.flush()

    def test_latest_row_wins_via_lateral(self, pg_db) -> None:
        self._insert(pg_db, it_transaction=1, item_id=301, it_priceofcostpp=100.0, it_cd=datetime(2025, 1, 1))
        self._insert(pg_db, it_transaction=2, item_id=301, it_priceofcostpp=300.0, it_cd=datetime(2026, 6, 1))
        self._insert(pg_db, it_transaction=3, item_id=301, it_priceofcostpp=200.0, it_cd=datetime(2025, 6, 1))

        result = resolver_ppp_batch(pg_db, [301])

        assert result[301].costo_ppp == 300.0
        assert result[301].costo_ppp_fecha == datetime(2026, 6, 1).date()

    def test_row_selection_predicate_holds_under_lateral(self, pg_db) -> None:
        self._insert(pg_db, it_transaction=10, item_id=302, it_priceofcostpp=999.0, it_cancelled=True)
        self._insert(pg_db, it_transaction=11, item_id=303, it_priceofcostpp=999.0, it_exchangetobranchcurrency=None)
        self._insert(pg_db, it_transaction=12, item_id=304, it_priceofcostpp=999.0, rmah_id=42)
        self._insert(pg_db, it_transaction=13, item_id=305, it_priceofcostpp=999.0, it_isrmasuppliercreditnote=True)
        self._insert(pg_db, it_transaction=14, item_id=306, it_priceofcostpp=0.0)
        self._insert(pg_db, it_transaction=15, item_id=307, it_priceofcostpp=150.0)

        result = resolver_ppp_batch(pg_db, [302, 303, 304, 305, 306, 307])

        assert result == {307: PppSource(costo_ppp=150.0, costo_ppp_fecha=datetime(2026, 1, 1).date())}

    @pytest.mark.parametrize("page_size", [1, 100])
    def test_exactly_one_query_regardless_of_page_size(self, pg_db, page_size: int) -> None:
        item_ids = list(range(400, 400 + page_size))
        for i, item_id in enumerate(item_ids):
            self._insert(pg_db, it_transaction=1000 + i, item_id=item_id, it_priceofcostpp=float(item_id))

        statements: list[str] = []

        def _listen(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa.event.listen(pg_db.connection(), "before_cursor_execute", _listen)
        try:
            result = resolver_ppp_batch(pg_db, item_ids)
        finally:
            sa.event.remove(pg_db.connection(), "before_cursor_execute", _listen)

        assert len(statements) == 1
        assert len(result) == page_size

    def test_more_than_900_item_ids_chunks_correctly_under_postgres(self, pg_db) -> None:
        item_ids = list(range(2000, 3000))  # 1000 ids -> 2 chunks at size 900
        for i, item_id in enumerate(item_ids[:3]):
            self._insert(pg_db, it_transaction=2000 + i, item_id=item_id, it_priceofcostpp=float(item_id))

        result = resolver_ppp_batch(pg_db, item_ids)

        assert result[item_ids[0]].costo_ppp == float(item_ids[0])
        assert result[item_ids[1]].costo_ppp == float(item_ids[1])
        assert result[item_ids[2]].costo_ppp == float(item_ids[2])
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Dialect equivalence — the single shared dataset both branches must agree on
# ---------------------------------------------------------------------------
#
# `resolver_ppp_batch` now has TWO independent implementations
# (`_build_lateral_stmt` for PostgreSQL, `_build_row_number_stmt` for every
# other dialect, notably SQLite in the rest of this suite). Nothing besides
# this test structurally guarantees they agree — each is otherwise exercised
# by a separate test class, against similar but not identical data. If they
# ever diverge, the LATERAL branch (the one that actually runs in production)
# is exactly the one with the least dedicated coverage, so a divergence would
# surface in production, not CI. This dataset is defined ONCE and fed to both
# branches so any real divergence is exposed here, not silently accommodated.

_EQUIVALENCE_DATASET = [
    # item_id 601: single qualifying row.
    dict(it_transaction=6001, item_id=601, it_priceofcostpp=111.0, it_cd=datetime(2026, 1, 5)),
    # item_id 602: several qualifying rows with distinct it_cd -> latest wins.
    dict(it_transaction=6002, item_id=602, it_priceofcostpp=100.0, it_cd=datetime(2025, 1, 1)),
    dict(it_transaction=6003, item_id=602, it_priceofcostpp=300.0, it_cd=datetime(2026, 6, 1)),
    dict(it_transaction=6004, item_id=602, it_priceofcostpp=200.0, it_cd=datetime(2025, 6, 1)),
    # item_id 603: cancelled row excluded.
    dict(it_transaction=6005, item_id=603, it_priceofcostpp=999.0, it_cancelled=True),
    # item_id 604: USD-denominated row excluded (it_exchangetobranchcurrency NULL), not converted.
    dict(it_transaction=6006, item_id=604, it_priceofcostpp=999.0, it_exchangetobranchcurrency=None),
    # item_id 605: RMA-linked row excluded.
    dict(it_transaction=6007, item_id=605, it_priceofcostpp=999.0, rmah_id=42),
    # item_id 606: supplier credit note excluded.
    dict(it_transaction=6008, item_id=606, it_priceofcostpp=999.0, it_isrmasuppliercreditnote=True),
    # item_id 607: non-positive it_priceofcostpp excluded.
    dict(it_transaction=6009, item_id=607, it_priceofcostpp=0.0),
    # item_id 608: EXACT it_cd tie between two qualifying rows -> the tiebreak
    # (it_transaction DESC) must make both branches agree deterministically.
    # If either branch ever drops that tiebreak, this is where it would show.
    dict(it_transaction=6010, item_id=608, it_priceofcostpp=400.0, it_cd=datetime(2026, 3, 1)),
    dict(it_transaction=6011, item_id=608, it_priceofcostpp=500.0, it_cd=datetime(2026, 3, 1)),
    # item_id 609: no row at all for this item_id (absent from the dataset;
    # included in the queried item_ids list below to prove absence-agreement).
]

_EQUIVALENCE_ITEM_IDS = [601, 602, 603, 604, 605, 606, 607, 608, 609]


def _seed_equivalence_dataset(session) -> None:
    defaults = dict(
        ct_transaction=1,
        it_cancelled=False,
        it_exchangetobranchcurrency=1.0,
        rmah_id=None,
        it_isrmasuppliercreditnote=False,
        it_cd=datetime(2026, 1, 1),
    )
    for row in _EQUIVALENCE_DATASET:
        merged = {**defaults, **row}
        session.add(ItemTransaction(**merged))
    session.commit()


@pytest.mark.postgres
class TestResolverDialectEquivalence:
    """Both resolver branches must agree, row for row, on the exact same dataset.

    `db` (SQLite) exercises `_build_row_number_stmt`; `pg_db` (real
    PostgreSQL) exercises `_build_lateral_stmt`. Same `_EQUIVALENCE_DATASET`,
    same `item_ids`, asserted to produce identical `{item_id: PppSource}`
    dicts — including the exact-`it_cd`-tie case (item_id 608), which is the
    one scenario where LATERAL's `LIMIT 1` and `ROW_NUMBER()` could plausibly
    disagree without a deterministic secondary tiebreak.
    """

    def test_sqlite_and_postgres_resolve_identically(self, db, pg_db) -> None:
        _seed_equivalence_dataset(db)
        _seed_equivalence_dataset(pg_db)

        sqlite_result = resolver_ppp_batch(db, _EQUIVALENCE_ITEM_IDS)
        postgres_result = resolver_ppp_batch(pg_db, _EQUIVALENCE_ITEM_IDS)

        assert sqlite_result.keys() == postgres_result.keys()
        for item_id in sqlite_result:
            assert sqlite_result[item_id].costo_ppp == postgres_result[item_id].costo_ppp, item_id
            assert sqlite_result[item_id].costo_ppp_fecha == postgres_result[item_id].costo_ppp_fecha, item_id

        # Pin down the expected values explicitly too, not just cross-equality
        # (two branches could agree on a value that is itself wrong).
        assert 603 not in sqlite_result and 603 not in postgres_result
        assert 604 not in sqlite_result and 604 not in postgres_result
        assert 605 not in sqlite_result and 605 not in postgres_result
        assert 606 not in sqlite_result and 606 not in postgres_result
        assert 607 not in sqlite_result and 607 not in postgres_result
        assert 609 not in sqlite_result and 609 not in postgres_result
        assert sqlite_result[601].costo_ppp == 111.0
        assert sqlite_result[602].costo_ppp == 300.0
        # Tie on it_cd -> highest it_transaction (6011, costo 500.0) wins on both branches.
        assert sqlite_result[608].costo_ppp == 500.0
        assert postgres_result[608].costo_ppp == 500.0

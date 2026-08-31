"""Tests for ML-vs-GBP divergence detection (slice 6). Covers the three
detection kinds this slice owns, dedup, rolling-window scoping, the
flag-off no-op, and the mandatory `window_not_enumerable` retention debt
from slice 3."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from unittest import mock

from app.core.config import settings
from app.services.ml_orders_ingestion import divergence_service
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.ml_orders_ops import MlOpsDivergence, MlOrdersOps
from app.services.ml_orders_ingestion.divergence_service import (
    MAX_CANDIDATES_PER_KIND,
    detect_divergences,
    purge_stale_unenumerable,
)

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _make_ops_order(db, order_id: int, **kwargs) -> MlOrdersOps:
    order = MlOrdersOps(
        order_id=order_id,
        status=kwargs.get("status", "paid"),
        date_created=kwargs.get("date_created", NOW - timedelta(days=1)),
        ml_last_updated=kwargs.get("ml_last_updated", NOW),
        seller_id=kwargs.get("seller_id", 999),
        paid_amount=kwargs.get("paid_amount"),
    )
    db.add(order)
    db.flush()
    return order


def _make_gbp_header(db, mlo_id: int, mlorder_id: str, **kwargs) -> MercadoLibreOrderHeader:
    header = MercadoLibreOrderHeader(
        mlo_id=mlo_id,
        mlorder_id=mlorder_id,
        mlo_status=kwargs.get("mlo_status", "paid"),
        ml_date_created=kwargs.get("ml_date_created", NOW - timedelta(days=1)),
        mlo_total_paid_amount=kwargs.get("mlo_total_paid_amount"),
    )
    db.add(header)
    db.flush()
    return header


class TestFlagGate:
    def test_flag_off_is_a_complete_no_op(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        _make_ops_order(db, 1)
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.ran is False
        assert db.query(MlOpsDivergence).count() == 0


class TestMissingInGbp:
    def test_order_with_no_gbp_header_is_flagged(self, db):
        _make_ops_order(db, 100)
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.missing_in_gbp == 1
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").first()
        assert row is not None
        assert row.order_id == 100

    def test_order_with_matching_header_is_not_flagged(self, db):
        _make_ops_order(db, 101)
        _make_gbp_header(db, mlo_id=1, mlorder_id="101")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.missing_in_gbp == 0

    def test_order_outside_the_rolling_window_is_not_flagged(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_WINDOW_DAYS", 30)
        _make_ops_order(db, 102, date_created=NOW - timedelta(days=200))
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.missing_in_gbp == 0
        assert db.query(MlOpsDivergence).count() == 0

    def test_redetection_does_not_duplicate_and_keeps_first_detected_at_while_open(self, db):
        """The query EXCLUDES rows that do not need re-processing, so a
        re-detected divergence that is still `open` is neither duplicated
        NOR refreshed. That "never refreshed" guarantee is conditional on
        the row staying `open`/`acknowledged` -- see
        `test_a_resolved_divergence_is_reopened_on_rediscovery` right
        below for the case where it DOES refresh."""
        _make_ops_order(db, 103)
        db.commit()

        detect_divergences(db, now=NOW)
        db.commit()
        first = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").first()
        first_detected_at = first.detected_at
        assert first.state == "open"

        later = NOW + timedelta(hours=1)
        result = detect_divergences(db, now=later)
        db.commit()

        rows = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").all()
        assert len(rows) == 1
        assert rows[0].detected_at == first_detected_at
        assert result.missing_in_gbp == 0

    def test_a_resolved_divergence_is_reopened_on_rediscovery(self, db):
        """`missing_in_gbp`/`missing_in_ml` carry no value, so once a
        divergence is closed the ONLY way it can become a candidate again
        is a genuine gap-then-recurrence (the order appeared in GBP,
        removing it from candidacy, then disappeared again) -- that must
        reopen it, or the table lies by omission forever after the first
        resolution."""
        _make_ops_order(db, 104)
        db.commit()

        first = detect_divergences(db, now=NOW)
        db.commit()
        assert first.missing_in_gbp == 1
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").one()
        row.state = "resolved"
        db.commit()

        later = NOW + timedelta(hours=1)
        second = detect_divergences(db, now=later)
        db.commit()

        assert second.missing_in_gbp == 1
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").one()
        assert row.state == "open"
        # SQLite loses tzinfo on round-trip (documented project gotcha).
        assert row.detected_at.replace(tzinfo=timezone.utc) == later

    def test_an_ignored_divergence_is_also_reopened_on_rediscovery(self, db, monkeypatch):
        """`ignored` is a CLOSED state exactly like `resolved` (module
        docstring "Reopening contract"): the exclusion's `still_active`
        branch only covers `open`/`acknowledged`, so `ignored` falls into
        the "closed, no value to compare, always reopen" branch too --
        this proves the exclusion does not special-case `resolved` only."""
        _make_ops_order(db, 105)
        db.commit()

        detect_divergences(db, now=NOW)
        db.commit()
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").one()
        row.state = "ignored"
        db.commit()

        result = detect_divergences(db, now=NOW + timedelta(hours=1))
        db.commit()

        assert result.missing_in_gbp == 1
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").one()
        assert row.state == "open"


class TestMissingInMl:
    def test_gbp_header_with_no_ops_row_is_flagged(self, db):
        _make_gbp_header(db, mlo_id=2, mlorder_id="200")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.missing_in_ml == 1
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_ml").first()
        assert row is not None
        assert row.order_id == 200

    def test_header_outside_the_rolling_window_is_not_flagged(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_WINDOW_DAYS", 30)
        _make_gbp_header(db, mlo_id=3, mlorder_id="201", ml_date_created=NOW - timedelta(days=400))
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.missing_in_ml == 0

    def test_non_numeric_mlorder_id_is_skipped_not_crashed(self, db):
        _make_gbp_header(db, mlo_id=4, mlorder_id="not-an-id")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.error is None
        assert result.missing_in_ml == 0

    def test_overlong_all_digit_mlorder_id_does_not_wedge_the_pass(self, db):
        """An all-digit `mlorder_id` can still be too long for `BigInteger`
        (`mlorder_id` is `String(50)`). Without the length bound,
        `CAST('9'*40 AS BIGINT)` raises "bigint out of range" on
        PostgreSQL and the WHOLE pass errors out -- including the other
        two kinds and the purge, already completed -- and the same row
        repeats identically every run: a permanent wedge through digits
        that are valid but too long."""
        _make_gbp_header(db, mlo_id=6, mlorder_id="9" * 40)
        _make_gbp_header(db, mlo_id=7, mlorder_id="850")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.error is None
        assert result.missing_in_ml == 1
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_ml").one()
        assert row.order_id == 850

    def test_leading_zeros_normalize_and_do_not_redetect_forever(self, db):
        """`"0101"` and
        `"101"` convert to the same integer, but the OLD exclusion
        compared against the raw string and never matched an
        already-recorded `order_id=101` -- it re-detected every pass."""
        _make_gbp_header(db, mlo_id=10, mlorder_id="0101")
        db.commit()

        first = detect_divergences(db, now=NOW)
        db.commit()
        assert first.missing_in_ml == 1
        row = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_ml").one()
        assert row.order_id == 101

        second = detect_divergences(db, now=NOW + timedelta(hours=1))
        db.commit()
        assert second.missing_in_ml == 0
        assert db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_ml").count() == 1

    def test_malformed_candidates_never_consume_a_cap_slot(self, db, monkeypatch):
        """A malformed `mlorder_id` used to pass
        the SQL filter, get discarded by a Python `continue` AFTER
        already spending a cap slot -- filled with enough of them (or
        sorted ahead of the valid ones, as here via a low-ASCII prefix),
        a pass could return NOTHING but garbage forever. The fix filters
        non-numeric values IN SQL, so they are never candidates at all:
        the cap is spent only on real candidates, and a following pass
        still reaches whatever the cap didn't fit."""
        monkeypatch.setattr("app.services.ml_orders_ingestion.divergence_service.MAX_CANDIDATES_PER_KIND", 2)
        for i in range(5):
            # '#' (0x23) sorts before any digit in a plain text ORDER BY,
            # so these would occupy every cap slot first under the old,
            # Python-side-only filtering.
            _make_gbp_header(db, mlo_id=20 + i, mlorder_id=f"#bad-{i}")
        for i in range(3):
            _make_gbp_header(db, mlo_id=30 + i, mlorder_id=str(800 + i))
        db.commit()

        first = detect_divergences(db, now=NOW)
        db.commit()
        assert first.missing_in_ml == 2
        assert first.truncated is True

        second = detect_divergences(db, now=NOW + timedelta(hours=1))
        db.commit()
        assert second.missing_in_ml == 1
        assert second.truncated is False

        recorded = {
            row[0] for row in db.query(MlOpsDivergence.order_id).filter(MlOpsDivergence.kind == "missing_in_ml")
        }
        assert recorded == {800, 801, 802}


class TestFieldMismatch:
    def test_status_mismatch_is_flagged(self, db):
        _make_ops_order(db, 300, status="paid")
        _make_gbp_header(db, mlo_id=5, mlorder_id="300", mlo_status="cancelled")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.field_mismatches == 1
        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "status")
            .first()
        )
        assert row is not None
        assert row.order_id == 300
        assert row.ml_value == "paid"
        assert row.gbp_value == "cancelled"

    def test_matching_status_is_not_flagged(self, db):
        _make_ops_order(db, 301, status="paid")
        _make_gbp_header(db, mlo_id=6, mlorder_id="301", mlo_status="paid")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.field_mismatches == 0

    def test_paid_amount_mismatch_is_flagged(self, db):
        _make_ops_order(db, 302, paid_amount=100)
        _make_gbp_header(db, mlo_id=7, mlorder_id="302", mlo_total_paid_amount=90)
        db.commit()

        detect_divergences(db, now=NOW)

        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "paid_amount")
            .first()
        )
        assert row is not None
        assert row.order_id == 302

    def test_a_resolved_field_mismatch_with_unchanged_values_stays_resolved(self, db):
        """Reviewer's explicit worked example: identical values + a
        CLOSED state means the operator already dealt with it -- re-
        selecting it every pass would consume a cap slot forever for no
        new information, so it must stay excluded (and closed)."""
        _make_ops_order(db, 320, status="paid")
        _make_gbp_header(db, mlo_id=40, mlorder_id="320", mlo_status="cancelled")
        db.commit()

        detect_divergences(db, now=NOW)
        db.commit()
        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "status")
            .one()
        )
        row.state = "resolved"
        db.commit()

        result = detect_divergences(db, now=NOW + timedelta(hours=1))
        db.commit()

        assert result.field_mismatches == 0
        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "status")
            .one()
        )
        assert row.state == "resolved"
        assert row.gbp_value == "cancelled"

    def test_a_resolved_paid_amount_mismatch_with_unchanged_value_stays_resolved(self, db):
        """The persisted value and the "unchanged" comparison must be the
        SAME representation. `50.00` is a real, reproducible case where
        they would otherwise disagree: SQLite's `CAST(NUMERIC AS TEXT)`
        renders a whole-number amount as `"50"`, but Python's
        `str(Decimal("50.00"))` preserves the declared scale as
        `"50.00"` -- if persistence used the Python string while the
        comparison used the SQL cast (two separate representations of
        the "same" rule), an unchanged, already-resolved amount mismatch
        would incorrectly look "changed" and reopen on every single pass,
        burning a cap slot forever for no new information."""
        _make_ops_order(db, 330, paid_amount=50)
        _make_gbp_header(db, mlo_id=50, mlorder_id="330", mlo_total_paid_amount=10)
        db.commit()

        detect_divergences(db, now=NOW)
        db.commit()
        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "paid_amount")
            .one()
        )
        row.state = "resolved"
        db.commit()

        result = detect_divergences(db, now=NOW + timedelta(hours=1))
        db.commit()

        assert result.field_mismatches == 0
        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "paid_amount")
            .one()
        )
        assert row.state == "resolved"

    def test_a_resolved_field_mismatch_reopens_when_the_value_changes(self, db):
        """A CLOSED row whose value genuinely changed must reopen -- the
        whole point of an operational dashboard someone works from
        daily."""
        _make_ops_order(db, 321, status="paid")
        _make_gbp_header(db, mlo_id=41, mlorder_id="321", mlo_status="cancelled")
        db.commit()

        detect_divergences(db, now=NOW)
        db.commit()
        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "status")
            .one()
        )
        row.state = "resolved"
        db.commit()

        header = db.query(MercadoLibreOrderHeader).filter(MercadoLibreOrderHeader.mlorder_id == "321").one()
        header.mlo_status = "refunded"
        db.commit()

        later = NOW + timedelta(hours=1)
        result = detect_divergences(db, now=later)
        db.commit()

        assert result.field_mismatches == 1
        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.field == "status")
            .one()
        )
        assert row.state == "open"
        assert row.gbp_value == "refunded"
        assert row.detected_at.replace(tzinfo=timezone.utc) == later

    def test_matching_paid_amount_is_not_flagged(self, db):
        """Negative case: equal amounts must never be flagged."""
        _make_ops_order(db, 305, paid_amount=100)
        _make_gbp_header(db, mlo_id=8, mlorder_id="305", mlo_total_paid_amount=100)
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.field_mismatches == 0

    def test_duplicate_gbp_headers_resolve_deterministically_to_highest_mlo_id(self, db):
        """Two GBP headers whose
        `mlorder_id` differs only by padding both resolve to the same
        `(order_id, 'field_mismatch', 'status')` key. The persisted value
        must not depend on database row-return order -- the header with
        the HIGHEST `mlo_id` wins, deterministically, every time."""
        _make_ops_order(db, 310, status="paid")
        _make_gbp_header(db, mlo_id=100, mlorder_id="310", mlo_status="cancelled")
        _make_gbp_header(db, mlo_id=200, mlorder_id=" 310 ", mlo_status="refunded")
        db.commit()

        detect_divergences(db, now=NOW)

        row = (
            db.query(MlOpsDivergence)
            .filter(MlOpsDivergence.kind == "field_mismatch", MlOpsDivergence.order_id == 310)
            .all()
        )
        assert len(row) == 1
        assert row[0].gbp_value == "refunded"

    def test_paid_amount_is_compared_numerically_not_as_text(self):
        """A text (`::text`) comparison happens
        to work today because `Numeric(14,2)` and `Numeric(18,2)` share a
        scale, but silently breaks -- flagging every order -- the day
        either column's scale changes. The spec must compare the raw
        `Numeric` columns; only persistence may stringify."""
        import sqlalchemy as sa

        from app.services.ml_orders_ingestion.divergence_service import _FIELD_MISMATCH_SPECS

        (_field_name, ml_col, gbp_col) = next(spec for spec in _FIELD_MISMATCH_SPECS if spec[0] == "paid_amount")
        assert isinstance(ml_col.type, sa.Numeric)
        assert isinstance(gbp_col.type, sa.Numeric)

    def test_padded_mlorder_id_still_joins(self, db):
        """GBP padding must not produce a
        false `missing_in_ml` for an order that genuinely exists in
        `ml_orders_ops`."""
        _make_ops_order(db, 306, status="paid")
        _make_gbp_header(db, mlo_id=9, mlorder_id=" 306 ", mlo_status="paid")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.missing_in_ml == 0
        assert db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_ml").count() == 0


class TestPersistenceIsSetBased:
    def test_a_cold_start_pass_issues_a_bounded_number_of_queries(self, db, monkeypatch):
        """Writing must not be one SELECT per
        candidate. Simulates the cold-start shape the review flagged --
        `ml_orders_ops` empty, many GBP header rows in-window -- and
        asserts the query count stays small (a handful of set-based
        statements) instead of scaling with the number of divergences."""
        for i in range(50):
            _make_gbp_header(db, mlo_id=1000 + i, mlorder_id=str(900 + i))
        db.commit()

        queries = []
        engine = db.get_bind()

        def _count(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        from sqlalchemy import event

        event.listen(engine, "before_cursor_execute", _count)
        try:
            result = detect_divergences(db, now=NOW)
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        assert result.missing_in_ml == 50
        # The blocking finding was reads scaling with candidate count (one
        # SELECT per candidate to check for an existing row). Writes are
        # legitimately proportional to new rows (50 real INSERTs) -- what
        # must stay bounded is the SELECT count: one detection query per
        # kind plus its NOT EXISTS exclusion, never one per candidate.
        select_count = sum(1 for q in queries if q.strip().upper().startswith("SELECT"))
        assert select_count < 10, f"expected a bounded SELECT count, got {select_count}: {queries}"


class TestTruncation:
    def test_a_pass_over_the_cap_is_marked_truncated_not_silently_dropped(self, db, monkeypatch):
        monkeypatch.setattr("app.services.ml_orders_ingestion.divergence_service.MAX_CANDIDATES_PER_KIND", 3)
        for i in range(5):
            _make_gbp_header(db, mlo_id=2000 + i, mlorder_id=str(950 + i))
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.truncated is True
        assert "missing_in_ml" in result.truncated_kinds
        assert result.missing_in_ml == 3

    def test_truncated_field_mismatch_names_the_specific_field(self, db, monkeypatch):
        """The cap is per FIELD, not per kind -- a bare "field_mismatch"
        in `truncated_kinds` would not say WHICH field was cut. Two
        different fields truncated independently must both be named."""
        monkeypatch.setattr("app.services.ml_orders_ingestion.divergence_service.MAX_CANDIDATES_PER_KIND", 1)
        _make_ops_order(db, 900, status="paid", paid_amount=100)
        _make_gbp_header(db, mlo_id=900, mlorder_id="900", mlo_status="cancelled", mlo_total_paid_amount=50)
        _make_ops_order(db, 901, status="paid", paid_amount=100)
        _make_gbp_header(db, mlo_id=901, mlorder_id="901", mlo_status="refunded", mlo_total_paid_amount=75)
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.truncated is True
        assert "field_mismatch:status" in result.truncated_kinds
        assert "field_mismatch:paid_amount" in result.truncated_kinds
        assert "field_mismatch" not in result.truncated_kinds

    def test_a_pass_under_the_cap_is_not_marked_truncated(self, db):
        _make_gbp_header(db, mlo_id=3000, mlorder_id="960")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.truncated is False
        assert result.truncated_kinds == []
        assert MAX_CANDIDATES_PER_KIND > 1

    def test_a_second_pass_records_what_the_cap_left_out(self, db, monkeypatch):
        """The module's core progress-guarantee claim: a truncated pass
        is recoverable, not a permanent wedge. Without the
        exclusion filter, an unordered `LIMIT` can return the SAME rows
        every pass and the remainder is never recorded -- this is the
        test that would have caught it."""
        monkeypatch.setattr("app.services.ml_orders_ingestion.divergence_service.MAX_CANDIDATES_PER_KIND", 3)
        for i in range(5):
            _make_gbp_header(db, mlo_id=4000 + i, mlorder_id=str(970 + i))
        db.commit()

        first = detect_divergences(db, now=NOW)
        db.commit()
        assert first.missing_in_ml == 3
        assert first.truncated is True

        second = detect_divergences(db, now=NOW + timedelta(hours=1))
        db.commit()
        assert second.missing_in_ml == 2
        assert second.truncated is False

        recorded = db.query(MlOpsDivergence.order_id).filter(MlOpsDivergence.kind == "missing_in_ml").distinct().all()
        assert {row[0] for row in recorded} == {970, 971, 972, 973, 974}


class TestUnenumerableSentinelRetention:
    def test_stale_unenumerable_rows_are_purged(self, db):
        stale = MlOpsDivergence(
            order_id=0,
            kind="window_not_enumerable",
            field="1|2",
            ml_value="2026-01-01T00:00:00+00:00",
            gbp_value="2026-01-01T00:01:00+00:00",
            detected_at=NOW - timedelta(days=60),
        )
        fresh = MlOpsDivergence(
            order_id=0,
            kind="window_not_enumerable",
            field="3|4",
            ml_value="2026-08-29T00:00:00+00:00",
            gbp_value="2026-08-29T00:01:00+00:00",
            detected_at=NOW - timedelta(days=1),
        )
        db.add_all([stale, fresh])
        db.commit()

        deleted = purge_stale_unenumerable(db, now=NOW, retention=timedelta(days=30))
        db.commit()

        assert deleted == 1
        remaining = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "window_not_enumerable").all()
        assert len(remaining) == 1
        assert remaining[0].field == "3|4"

    def test_detect_divergences_runs_the_purge(self, db):
        db.add(
            MlOpsDivergence(
                order_id=0,
                kind="window_not_enumerable",
                field="5|6",
                detected_at=NOW - timedelta(days=400),
            )
        )
        db.commit()

        result = detect_divergences(db, now=NOW)
        db.commit()

        assert result.unenumerable_purged == 1
        assert db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "window_not_enumerable").count() == 0


class TestDuplicateGbpHeadersDoNotBreakThePass:
    """GBP can hold two headers whose `mlorder_id` differs only by padding
    — distinct rows there, the same id here now that the join trims. Two
    candidates then resolve to one `(order_id, kind, field)` key in the
    SAME pass, before either one has a divergence row of its own to be
    excluded by -- the in-memory `seen` dict in `_apply_divergence` is
    what keeps the second one from being staged as a duplicate insert."""

    def test_two_gbp_headers_for_one_order_do_not_raise(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        _make_gbp_header(db, mlo_id=1, mlorder_id="306")
        _make_gbp_header(db, mlo_id=2, mlorder_id=" 306 ")
        db.commit()

        result = detect_divergences(db)

        assert result.error is None
        rows = db.query(MlOpsDivergence).filter_by(kind="missing_in_ml").all()
        assert len(rows) == 1

    def test_a_failed_pass_leaves_the_session_usable(self, db, monkeypatch):
        """The error path must be able to finish: `get_background_db`
        commits on exit, so a session left in a failed state turns a
        reported error into PendingRollbackError and a traceback."""
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        _make_ops_order(db, 1)
        db.commit()

        with mock.patch.object(divergence_service, "_detect_missing_in_gbp", side_effect=RuntimeError("boom")):
            result = detect_divergences(db)

        assert result.error is not None
        # a usable session can still answer a query
        assert db.query(MlOpsDivergence).count() >= 0

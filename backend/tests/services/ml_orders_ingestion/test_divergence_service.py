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

    def test_redetection_does_not_duplicate_and_keeps_first_detected_at(self, db):
        """Round 2: the query now EXCLUDES already-recorded rows (the
        fix for finding 1's permanent-truncation bug), so a re-detected
        divergence is neither duplicated NOR refreshed -- `detected_at`
        means "first detected" now, documented in the module docstring's
        "Consequence" section."""
        _make_ops_order(db, 103)
        db.commit()

        detect_divergences(db, now=NOW)
        db.commit()
        first = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").first()
        first_detected_at = first.detected_at

        later = NOW + timedelta(hours=1)
        result = detect_divergences(db, now=later)
        db.commit()

        rows = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").all()
        assert len(rows) == 1
        assert rows[0].detected_at == first_detected_at
        assert result.missing_in_gbp == 0


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

    def test_matching_paid_amount_is_not_flagged(self, db):
        """Negative case: equal amounts must never be flagged."""
        _make_ops_order(db, 305, paid_amount=100)
        _make_gbp_header(db, mlo_id=8, mlorder_id="305", mlo_total_paid_amount=100)
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.field_mismatches == 0

    def test_duplicate_gbp_headers_resolve_deterministically_to_highest_mlo_id(self, db):
        """Round 2 non-blocking finding 3: two GBP headers whose
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
        """Pre-push review finding 3: a text (`::text`) comparison happens
        to work today because `Numeric(14,2)` and `Numeric(18,2)` share a
        scale, but silently breaks -- flagging every order -- the day
        either column's scale changes. The spec must compare the raw
        `Numeric` columns; only persistence may stringify."""
        import sqlalchemy as sa

        from app.services.ml_orders_ingestion.divergence_service import _FIELD_MISMATCH_SPECS

        (field_name, ml_col, gbp_col) = next(spec for spec in _FIELD_MISMATCH_SPECS if spec[0] == "paid_amount")
        assert isinstance(ml_col.type, sa.Numeric)
        assert isinstance(gbp_col.type, sa.Numeric)

    def test_padded_mlorder_id_still_joins(self, db):
        """Pre-push review finding 4: GBP padding must not produce a
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
        """Pre-push review finding 1: writing must not be one SELECT per
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
        # kind plus one preload query per kind, never one per candidate.
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

    def test_a_pass_under_the_cap_is_not_marked_truncated(self, db):
        _make_gbp_header(db, mlo_id=3000, mlorder_id="960")
        db.commit()

        result = detect_divergences(db, now=NOW)

        assert result.truncated is False
        assert result.truncated_kinds == []
        assert MAX_CANDIDATES_PER_KIND > 1

    def test_a_second_pass_records_what_the_cap_left_out(self, db, monkeypatch):
        """The docstring's core claim (round 2 blocking finding 1): a
        truncated pass is recoverable, not a permanent wedge. Without the
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
    candidates then resolve to one `(order_id, kind, field)` key, and the
    preload dict never learns about a row staged earlier in the same pass."""

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

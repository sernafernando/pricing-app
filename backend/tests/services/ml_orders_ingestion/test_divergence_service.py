"""Tests for ML-vs-GBP divergence detection (slice 6). Covers the three
detection kinds this slice owns, dedup, rolling-window scoping, the
flag-off no-op, and the mandatory `window_not_enumerable` retention debt
from slice 3."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.ml_orders_ops import MlOpsDivergence, MlOrdersOps
from app.services.ml_orders_ingestion.divergence_service import (
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

    def test_redetection_updates_instead_of_duplicating(self, db):
        _make_ops_order(db, 103)
        db.commit()

        detect_divergences(db, now=NOW)
        db.commit()
        first = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").first()
        first_detected_at = first.detected_at

        later = NOW + timedelta(hours=1)
        detect_divergences(db, now=later)
        db.commit()

        rows = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == "missing_in_gbp").all()
        assert len(rows) == 1
        assert rows[0].detected_at > first_detected_at


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

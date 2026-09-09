"""
RED/GREEN -- `MlOpsSyncCursor.activity_cursor` (ml-activity-receiver
slice 2).

Spec coverage:
  REQ-1 -- the column round-trips a plain string value.
  REQ-2 -- `activity_cursor` SURVIVES `release_lock_as_idle(complete=False)`
           (a truncated drain pass), because that helper writes only
           `state` and `detail`. This is the column's whole reason for
           NOT living inside `detail`: `detail` gets overwritten on every
           pass, `activity_cursor` must not.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.ml_orders_ops import MlOpsSyncCursor
from app.services.ml_orders_ingestion import sweep_service


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


class TestActivityCursorRoundTrips:
    def test_value_persists_across_reload(self, db) -> None:
        db.add(MlOpsSyncCursor(name="ml_activity", state="idle", activity_cursor="a1|2"))
        db.commit()

        db.expire_all()
        row = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").first()

        assert row.activity_cursor == "a1|2"

    def test_null_means_never_drained(self, db) -> None:
        db.add(MlOpsSyncCursor(name="ml_activity", state="idle"))
        db.commit()

        db.expire_all()
        row = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").first()

        assert row.activity_cursor is None


class TestActivityCursorSurvivesTruncatedRelease:
    def test_survives_release_lock_as_idle_incomplete(self, db, monkeypatch) -> None:
        monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))

        db.add(MlOpsSyncCursor(name="ml_activity", state="running", activity_cursor="a1|2"))
        db.commit()

        sweep_service.release_lock_as_idle(datetime.now(timezone.utc), complete=False, cursor_name="ml_activity")

        row = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").first()

        assert row.activity_cursor == "a1|2"
        assert row.state == "idle"
        assert row.detail == "stopped early: fetch budget exhausted"

    def test_survives_release_lock_as_idle_complete(self, db, monkeypatch) -> None:
        monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))

        db.add(MlOpsSyncCursor(name="ml_activity", state="running", activity_cursor="a1|2"))
        db.commit()

        sweep_service.release_lock_as_idle(datetime.now(timezone.utc), complete=True, cursor_name="ml_activity")

        row = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").first()

        assert row.activity_cursor == "a1|2"
        assert row.detail is None

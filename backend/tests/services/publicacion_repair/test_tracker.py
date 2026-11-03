"""finish_run status classification for repair tracker."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.publicacion_repair import (
    ACTION_SKIPPED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
)
from app.services.publicacion_repair.tracker import finish_run, record_event


def _run() -> SimpleNamespace:
    return SimpleNamespace(
        scanned=0,
        changed=0,
        skipped=0,
        errors=0,
        error_message=None,
        finished_at=None,
        status="running",
    )


def test_finish_run_success_with_skips_only() -> None:
    out = finish_run(MagicMock(), _run(), scanned=10, changed=0, skipped=3, errors=0)
    assert out.status == STATUS_SUCCESS


def test_finish_run_partial_when_errors_and_changes() -> None:
    out = finish_run(MagicMock(), _run(), scanned=10, changed=2, skipped=1, errors=3)
    assert out.status == STATUS_PARTIAL


def test_finish_run_failed_when_fatal_before_scan() -> None:
    out = finish_run(
        MagicMock(),
        _run(),
        scanned=0,
        changed=0,
        skipped=0,
        errors=1,
        error_message="boom",
    )
    assert out.status == STATUS_FAILED


def test_record_event_jsonifies_datetimes_in_before_after() -> None:
    db = MagicMock()
    ts = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    record_event(
        db,
        run_id=1,
        mla_id="MLA1",
        action=ACTION_SKIPPED,
        before={"fetched_at": ts, "tags": []},
        after={"fingerprint": "x", "nested": {"at": ts}},
        detail="flex_refused",
    )
    event = db.add.call_args[0][0]
    assert event.before == {"fetched_at": ts.isoformat(), "tags": []}
    assert event.after == {"fingerprint": "x", "nested": {"at": ts.isoformat()}}

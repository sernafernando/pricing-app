"""finish_run status classification for repair tracker."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.publicacion_repair import STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS
from app.services.publicacion_repair.tracker import finish_run


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

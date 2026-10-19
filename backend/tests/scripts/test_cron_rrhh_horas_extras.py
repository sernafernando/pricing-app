"""The manual HE script is a thin wrapper over the shared daily run (the worker schedules it)."""

from __future__ import annotations

from datetime import date

import pytest

from app.scripts import cron_rrhh_horas_extras as script
from app.services import rrhh_horas_extras_diario as diario


class _Runs(list):
    """The days the wrapper ran, plus the status the fake run answers with."""

    status = diario.STATUS_OK


@pytest.fixture()
def runs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _Runs:
    monkeypatch.setattr(script, "LOCK_PATH_PRIMARY", tmp_path / "he.lock")
    monkeypatch.setattr(script, "LOCK_PATH_FALLBACK", tmp_path / "he-fallback.lock")
    called = _Runs()

    def fake_run(day, **_):
        called.append(day)
        return diario.DailyRunResult(day=day, status=called.status)

    monkeypatch.setattr(script, "run_daily_detection", fake_run)
    return called


def test_it_reruns_the_given_day(runs) -> None:
    assert script.main(["--fecha", "2026-05-05"]) == 0
    assert runs == [date(2026, 5, 5)]


def test_without_a_day_it_runs_yesterday_in_argentina(runs, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "previous_local_day", lambda now: date(2026, 10, 18))
    assert script.main([]) == 0
    assert runs == [date(2026, 10, 18)]


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [(diario.STATUS_DISABLED, 3), (diario.STATUS_DETECTION_FAILED, 2), (diario.STATUS_OK, 0)],
)
def test_exit_codes_follow_the_run_status(runs, status, exit_code) -> None:
    runs.status = status
    assert script.main(["--fecha", "2026-05-05"]) == exit_code

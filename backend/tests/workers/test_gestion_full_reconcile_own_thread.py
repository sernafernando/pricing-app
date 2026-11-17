"""RED/GREEN -- `gestion_full.reconcile` must never block the ML worker's drain pass.

Prod, 2026-11-17 (`pricing-worker-ml`): the reconcile ran in the drain pass, waited minutes on the shared ML
pacer for one envío with 18 inventories, then failed (`server closed the connection unexpectedly`). A failed run
left `last_success_at` old, so every following pass ran it again; `ml_publications.intake` and `freshness`
starved and every ML resource fell ~11 minutes behind.
"""

from __future__ import annotations

from datetime import timedelta
from typing import List

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.gestion_full_reconcile import GestionFullReconcileHandler
from app.workers.runtime import WorkerRuntime


class _Recorder:
    """Channel-driven, so `drain_once` runs it on every pass."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.channels: tuple = ("test_channel",)
        self.interval = None
        self.run_at_local = None
        self.runs = 0

    def run(self, ctx: WorkerContext) -> JobResult:
        self.runs += 1
        return JobResult(success=True)


class _FailingSessions:
    """Every session the reconcile opens fails, like the dropped connection in prod."""

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self):
        self.opened += 1
        raise RuntimeError("server closed the connection unexpectedly")


class _StopAfterFirstWait:
    """Stands in for the runtime's stop event: records each pause and stops the loop on the first one."""

    def __init__(self) -> None:
        self.pauses: List[float] = []
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def wait(self, seconds: float) -> bool:
        self.pauses.append(seconds)
        self._set = True
        return True


@pytest.fixture()
def pg_runtime_db(monkeypatch, pg_worker_engine):
    session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state"))
    yield pg_worker_engine
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state"))


@pytest.mark.postgres
class TestReconcileNeverBlocksTheDrainPass:
    def test_a_failing_reconcile_does_not_run_in_the_pass_and_intake_and_freshness_still_run(
        self, pg_runtime_db
    ) -> None:
        sessions = _FailingSessions()
        reconcile = GestionFullReconcileHandler(session_factory=sessions)
        intake = _Recorder("ml_publications.intake")
        freshness = _Recorder("ml_publications.freshness")
        runtime = WorkerRuntime(registry=[reconcile, intake, freshness], direct_url=None)

        runtime.drain_once()
        runtime.drain_once()

        assert sessions.opened == 0
        assert intake.runs == 2
        assert freshness.runs == 2

    def test_a_failing_reconcile_runs_once_then_waits_three_hours_before_retrying(self, pg_runtime_db) -> None:
        sessions = _FailingSessions()
        reconcile = GestionFullReconcileHandler(session_factory=sessions)
        runtime = WorkerRuntime(registry=[reconcile], direct_url=None)
        stop = _StopAfterFirstWait()
        runtime._stop_event = stop

        runtime._own_thread_loop(reconcile)

        assert sessions.opened == 1
        assert stop.pauses == [timedelta(hours=3).total_seconds()]
        with pg_runtime_db.begin() as conn:
            row = conn.execute(
                text("SELECT last_run_at, last_success_at FROM worker_job_state WHERE name = 'gestion_full.reconcile'")
            ).one()
        assert row.last_run_at is not None
        assert row.last_success_at is None

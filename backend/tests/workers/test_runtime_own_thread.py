"""ml-sync-pipeline T4 (S3+S4): a handler marked `own_thread` runs in its own thread of the worker, with the
deadline it declares (`deadline_seconds`), instead of taking its turn in the drain pass with the generic 30 s.

Prod, 2026-10-26 (`pricing-worker-ml`): `ml_publications.refresh` claimed 20 entries, was cut at 30 s, then waited
for ten other handlers before its next turn: on the order of 10 ML calls per minute against a 2/s budget.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers.context import JobResult, WorkerContext
from app.workers.runtime import HEARTBEAT_DEATH_EXIT_CODE, WorkerRuntime


class _Handler:
    def __init__(
        self,
        name: str,
        *,
        own_thread: bool = False,
        deadline_seconds: Optional[float] = None,
        on_run=None,
    ) -> None:
        self.name = name
        self.channels: tuple = () if own_thread else ("test_channel",)
        self.interval = timedelta(seconds=5) if own_thread else None
        self.run_at_local = None
        if own_thread:
            self.own_thread = True
        if deadline_seconds is not None:
            self.deadline_seconds = deadline_seconds
        self.contexts: List[WorkerContext] = []
        self.started_at: List[datetime] = []
        self.threads: List[str] = []
        self._on_run = on_run

    def run(self, ctx: WorkerContext) -> JobResult:
        self.contexts.append(ctx)
        self.started_at.append(datetime.now(timezone.utc))
        self.threads.append(threading.current_thread().name)
        if self._on_run is not None:
            self._on_run(ctx)
        return JobResult(success=True)


@pytest.fixture()
def pg_runtime_db(monkeypatch, pg_worker_engine):
    session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state"))
    yield pg_worker_engine
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state"))


def _blocking(started: threading.Event, release: threading.Event):
    def run(ctx: WorkerContext) -> None:
        started.set()
        assert release.wait(5)

    return run


@pytest.mark.postgres
class TestOwnThreadHandlers:
    def test_the_drain_pass_never_runs_an_own_thread_handler(self, pg_runtime_db) -> None:
        own = _Handler("ml_publications.refresh", own_thread=True)
        other = _Handler("ml_publications.scan")

        WorkerRuntime(registry=[own, other], direct_url=None).drain_once()

        assert own.contexts == []
        assert len(other.contexts) == 1

    def test_the_other_handlers_keep_running_while_it_is_busy(self, pg_runtime_db) -> None:
        started, release = threading.Event(), threading.Event()
        own = _Handler("ml_publications.refresh", own_thread=True, on_run=_blocking(started, release))
        other = _Handler("ml_publications.scan")
        runtime = WorkerRuntime(registry=[own, other], direct_url=None)

        runtime.start_own_threads()
        try:
            assert started.wait(5)
            runtime.drain_once()
            runtime.drain_once()
            assert len(other.contexts) == 2  # never waited for the busy handler
            assert own.threads[0] != threading.current_thread().name
        finally:
            runtime.stop()
            release.set()
            runtime.join_own_threads(timeout=5)

    def test_it_gets_the_deadline_it_declares(self, pg_runtime_db) -> None:
        started, release = threading.Event(), threading.Event()
        own = _Handler(
            "ml_publications.refresh", own_thread=True, deadline_seconds=150, on_run=_blocking(started, release)
        )
        runtime = WorkerRuntime(registry=[own], direct_url=None)

        runtime.start_own_threads()
        try:
            assert started.wait(5)
            budget = own.contexts[0].deadline - own.started_at[0]
            assert timedelta(seconds=149) < budget <= timedelta(seconds=150)
        finally:
            runtime.stop()
            release.set()
            runtime.join_own_threads(timeout=5)

    def test_a_stop_is_visible_to_the_running_handler(self, pg_runtime_db) -> None:
        started, release = threading.Event(), threading.Event()
        own = _Handler("ml_publications.refresh", own_thread=True, on_run=_blocking(started, release))
        runtime = WorkerRuntime(registry=[own], direct_url=None)

        runtime.start_own_threads()
        assert started.wait(5)
        ctx = own.contexts[0]
        assert ctx.stop_requested() is False
        runtime.stop()
        assert ctx.stop_requested() is True
        release.set()
        runtime.join_own_threads(timeout=5)

    def test_a_dead_own_thread_makes_the_worker_exit_for_systemd_to_restart(self, pg_runtime_db) -> None:
        def die(ctx: WorkerContext) -> None:
            raise SystemExit("thread killed")

        own = _Handler("ml_publications.refresh", own_thread=True, on_run=die)
        runtime = WorkerRuntime(registry=[own], direct_url=None)
        runtime.start_own_threads()
        runtime.join_own_threads(timeout=5)

        with pytest.raises(SystemExit) as exited:
            runtime._check_heartbeat_or_die()
        assert exited.value.code == HEARTBEAT_DEATH_EXIT_CODE

    def test_an_on_demand_request_is_cleared_by_its_own_thread_after_a_successful_run(self, pg_runtime_db) -> None:
        with pg_runtime_db.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, state) VALUES ('ml_publications.refresh', 'requested')")
            )
        ran = threading.Event()
        own = _Handler("ml_publications.refresh", own_thread=True, on_run=lambda ctx: ran.set())
        runtime = WorkerRuntime(registry=[own], direct_url=None)

        runtime.start_own_threads()
        assert ran.wait(5)
        runtime.stop()
        runtime.join_own_threads(timeout=5)

        with pg_runtime_db.connect() as conn:
            state = conn.execute(
                text("SELECT state FROM worker_job_state WHERE name = 'ml_publications.refresh'")
            ).scalar()
        assert state is None

    def test_its_thread_never_keeps_the_process_alive_past_the_stop_join(self, pg_runtime_db) -> None:
        started, release = threading.Event(), threading.Event()
        own = _Handler("ml_publications.refresh", own_thread=True, on_run=_blocking(started, release))
        runtime = WorkerRuntime(registry=[own], direct_url=None)

        runtime.start_own_threads()
        try:
            assert started.wait(5)
            assert all(thread.daemon for thread in runtime._own_threads)
        finally:
            runtime.stop()
            release.set()
            runtime.join_own_threads(timeout=5)

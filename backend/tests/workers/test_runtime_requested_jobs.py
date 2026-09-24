"""RED/GREEN -- `WorkerRuntime` on-demand job pickup (ventas-ml-rediseno
PR6.T8/T9, design D10): `POST /order-metrics/divergence/run` sets
`worker_job_state.state='requested'` and `pg_notify('worker_jobs', name)`;
the worker LISTENs on `worker_jobs` unconditionally and runs any handler
whose row is `state='requested'` on its next drain pass, clearing the flag.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers.context import JobResult
from app.workers.runtime import WorkerRuntime


class _FakeHandler:
    def __init__(self, name: str) -> None:
        self.name = name
        self.channels: tuple = ()
        self.interval = None
        self.run_at_local = None
        self.run = MagicMock(return_value=JobResult(success=True))


@pytest.mark.postgres
class TestListensOnWorkerJobsChannel:
    def test_open_listener_connection_listens_on_worker_jobs(self, pg_worker_engine) -> None:
        from tests.conftest import POSTGRES_TEST_URL

        runtime = WorkerRuntime(registry=[], direct_url=POSTGRES_TEST_URL)
        conn = runtime._open_listener_connection()
        try:
            cur = conn.cursor()
            # A LISTEN issued twice on the same channel/connection is a
            # harmless no-op in Postgres -- this proves the channel was
            # already registered by `_open_listener_connection` itself.
            cur.execute("NOTIFY worker_jobs, 'order_metrics.divergence'")
            conn.poll()
            assert any(n.channel == "worker_jobs" for n in conn.notifies)
        finally:
            conn.close()


@pytest.mark.postgres
class TestRequestedHandlerPickup:
    def test_requested_handler_runs_and_flag_is_cleared(self, monkeypatch, pg_worker_engine) -> None:
        session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr("app.core.database.SessionLocal", session_factory)

        handler = _FakeHandler("order_metrics.divergence")
        runtime = WorkerRuntime(registry=[handler], direct_url=None)

        with pg_worker_engine.connect() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, state) VALUES ('order_metrics.divergence', 'requested')")
            )
            conn.commit()

        runtime.drain_once()

        handler.run.assert_called_once()

        with pg_worker_engine.connect() as conn:
            row = conn.execute(
                text("SELECT state FROM worker_job_state WHERE name = 'order_metrics.divergence'")
            ).fetchone()
        assert row.state is None

    def test_non_requested_handler_is_not_run_by_the_requested_path(self, monkeypatch, pg_worker_engine) -> None:
        session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr("app.core.database.SessionLocal", session_factory)

        handler = _FakeHandler("order_metrics.reconcile")
        runtime = WorkerRuntime(registry=[handler], direct_url=None)

        runtime.drain_once()

        handler.run.assert_not_called()

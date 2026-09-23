"""RED/GREEN -- `WorkerRuntime` (ventas-ml-rediseno PR2.T3/T4/T8, design D4):
LISTEN via `DATABASE_URL_DIRECT` bypasses PgBouncer; unset -> `poll_only`
mode with a logged WARNING (never silent loss). With the registry still
EMPTY (PR2), a full idle loop runs and idles harmlessly.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers.runtime import WorkerRuntime


@pytest.mark.postgres
class TestListenerModeAndDirectUrl:
    def test_notify_mode_with_direct_url_opens_a_real_listen_connection(self, pg_worker_engine) -> None:
        """`DATABASE_URL_DIRECT` set -> `listener_mode == 'notify'`, and the
        runtime can actually issue LISTEN against it (bypassing PgBouncer,
        which is exactly what a plain psycopg2 connection to the test
        Postgres instance proves here -- no PgBouncer sits in front of the
        test DB, but this connection is the SAME kind of raw, non-pooled
        connection production points at `DATABASE_URL_DIRECT`)."""
        from tests.conftest import POSTGRES_TEST_URL

        runtime = WorkerRuntime(registry=[], direct_url=POSTGRES_TEST_URL)
        assert runtime.listener_mode == "notify"

        conn = runtime._open_listener_connection()
        try:
            assert conn.closed == 0
        finally:
            conn.close()

    def test_poll_only_mode_when_direct_url_unset_logs_a_warning(self, caplog) -> None:
        runtime = WorkerRuntime(registry=[], direct_url=None, safety_poll_interval=0.05)
        assert runtime.listener_mode == "poll_only"

        stop_after = threading.Timer(0.15, runtime.stop)
        with caplog.at_level(logging.WARNING, logger="app.workers.runtime"):
            stop_after.start()
            runtime.run_forever()

        assert any("poll_only" in record.message for record in caplog.records)


@pytest.mark.postgres
class TestIdleLoopWithEmptyRegistry:
    def test_worker_idles_harmlessly_and_heartbeat_updates(self, monkeypatch, pg_worker_engine) -> None:
        """PR2's registry ships EMPTY -- the worker must still run its full
        loop (heartbeat thread, drain pass, safety poll) without crashing,
        and the heartbeat must be visibly alive in `worker_job_state`."""
        session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr("app.core.database.SessionLocal", session_factory)

        runtime = WorkerRuntime(registry=[], worker_name="idle-test-worker", direct_url=None, safety_poll_interval=0.05)
        thread = threading.Thread(target=runtime.run_forever)
        thread.start()
        try:
            time.sleep(0.3)
            assert thread.is_alive() is True
            assert runtime.heartbeat is not None
            assert runtime.heartbeat.is_healthy() is True

            with pg_worker_engine.connect() as conn:
                row = conn.execute(
                    text("SELECT heartbeat_at FROM worker_job_state WHERE name = 'idle-test-worker'")
                ).fetchone()
            assert row is not None
        finally:
            runtime.stop()
            thread.join(timeout=3)
            assert thread.is_alive() is False
            with pg_worker_engine.connect() as conn:
                conn.execute(text("DELETE FROM worker_job_state WHERE name = 'idle-test-worker'"))
                conn.commit()

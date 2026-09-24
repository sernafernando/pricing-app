"""RED/GREEN -- `WorkerRuntime` (ventas-ml-rediseno PR2.T3/T4/T8, design D4):
LISTEN via `DATABASE_URL_DIRECT` bypasses PgBouncer; unset -> `poll_only`
mode with a logged WARNING (never silent loss). With the registry still
EMPTY (PR2), a full idle loop runs and idles harmlessly.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers.runtime import WorkerRuntime


class _StubCatchUpHandler:
    """A `run_at_local` handler that ALSO declares `catch_up_interval`
    (`order_metrics.divergence`'s real shape, PR6 review fix J4)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.channels: tuple = ()
        self.interval = None
        from datetime import time as dtime

        self.run_at_local = dtime(4, 0)
        self.catch_up_interval = timedelta(minutes=2)


@pytest.mark.postgres
class TestDueHandlersReadsIncompleteFromPersistedDetail:
    """PR6 review fix J4: `_due_handlers` must read the handler's own
    persisted `detail.complete` flag and pass `incomplete=` into
    `scheduling.is_due`, so a `catch_up_interval` handler becomes due off
    its daily slot while the last lap is unfinished -- otherwise ~77k
    orders would need 23+ hours between each on-demand click."""

    def test_handler_is_due_off_slot_when_last_summary_is_incomplete(self, monkeypatch, pg_worker_engine) -> None:
        session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr("app.core.database.SessionLocal", session_factory)

        handler = _StubCatchUpHandler("order_metrics.divergence")
        runtime = WorkerRuntime(registry=[handler], direct_url=None)

        now = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)  # 14:00 AR -- off the 04:00 slot
        with pg_worker_engine.connect() as conn:
            conn.execute(text("DELETE FROM worker_job_state WHERE name = 'order_metrics.divergence'"))
            conn.execute(
                text(
                    "INSERT INTO worker_job_state (name, last_success_at, detail) "
                    "VALUES ('order_metrics.divergence', :last_success_at, "
                    "CAST(:detail AS JSONB))"
                ),
                {"last_success_at": now - timedelta(minutes=5), "detail": '{"complete": false}'},
            )
            conn.commit()

        # `now` here is far off the 04:00 AR daily slot -- the ONLY reason
        # this is due is the persisted `complete=False` unlocking the
        # short catch-up cadence.
        due = runtime._due_handlers(now)
        assert handler in due

    def test_handler_is_not_due_off_slot_when_last_summary_is_complete(self, monkeypatch, pg_worker_engine) -> None:
        session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr("app.core.database.SessionLocal", session_factory)

        handler = _StubCatchUpHandler("order_metrics.divergence")
        runtime = WorkerRuntime(registry=[handler], direct_url=None)

        now = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)  # 14:00 AR -- off the 04:00 slot
        with pg_worker_engine.connect() as conn:
            conn.execute(text("DELETE FROM worker_job_state WHERE name = 'order_metrics.divergence'"))
            conn.execute(
                text(
                    "INSERT INTO worker_job_state (name, last_success_at, detail) "
                    "VALUES ('order_metrics.divergence', :last_success_at, "
                    "CAST(:detail AS JSONB))"
                ),
                {"last_success_at": now - timedelta(minutes=5), "detail": '{"complete": true}'},
            )
            conn.commit()

        due = runtime._due_handlers(now)
        # A completed lap must fall back to the plain daily slot -- the
        # short catch-up cadence must not fire when there is nothing left
        # to catch up on.
        assert handler not in due


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

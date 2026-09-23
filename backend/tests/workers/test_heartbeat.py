"""RED/GREEN -- `HeartbeatThread` (ventas-ml-rediseno PR2.T4a/T4b, design D4
step 5): a dedicated thread renews `worker_job_state.heartbeat_at`
independently of whatever the main thread is doing, and its own death (or a
stalled tick) is detectable by `is_healthy()`.

Real Postgres: the heartbeat's `ON CONFLICT` upsert and the fenced lease
renewal UPDATE are Postgres-only statements (`ml_order_metrics_dirty`'s
`claim_token = ANY(:tokens)` fence).

Intervals are scaled down from the design's real 5s tick / 30s dead-window
so this test runs in well under a second; the mechanism under test
(liveness independent of a slow "main thread", detection of a wedged tick)
is identical at any timescale.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.workers.heartbeat import HeartbeatThread


@pytest.fixture()
def _worker_db_session(monkeypatch, pg_worker_engine):
    """Points `app.core.database.SessionLocal` (what `get_background_db()`
    binds to) at `pg_worker_engine` for the duration of one test, so the
    heartbeat thread's own short blocks land on the real Postgres fixture
    tables instead of the app's configured `DATABASE_URL`."""
    session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    yield
    with pg_worker_engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("DELETE FROM worker_job_state"))
        conn.execute(__import__("sqlalchemy").text("DELETE FROM ml_order_metrics_dirty"))
        conn.commit()


@pytest.mark.postgres
class TestHeartbeatStaysAliveWhileMainThreadBlocked:
    def test_heartbeat_at_keeps_advancing_while_a_stubbed_handler_blocks(
        self, _worker_db_session, pg_worker_engine
    ) -> None:
        thread = HeartbeatThread(worker_name="test-worker", interval=0.05)
        thread.start()
        try:
            # Simulate the main thread stuck inside a long handler call --
            # the heartbeat must keep ticking on its own regardless.
            time.sleep(0.3)
            assert thread.is_healthy() is True

            with pg_worker_engine.connect() as conn:
                row = conn.execute(
                    __import__("sqlalchemy").text(
                        "SELECT heartbeat_at FROM worker_job_state WHERE name = 'test-worker'"
                    )
                ).fetchone()
            assert row is not None
            heartbeat_at = row[0]
            if heartbeat_at.tzinfo is None:
                heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
            assert (datetime.now(timezone.utc) - heartbeat_at).total_seconds() < 1.0
        finally:
            thread.stop()
            thread.join(timeout=2)

    def test_lease_renewal_hook_called_each_tick_with_held_tokens(self, _worker_db_session, pg_worker_engine) -> None:
        """PR2 registry is empty so no real claim exists yet, but the
        renewal hook itself (design D4 step 5's `renew_leases` UPDATE,
        fenced by `claim_token`) must run every tick against whatever the
        in-process token set currently holds -- PR3's drain handler is the
        first real caller."""
        token = uuid.uuid4()
        with pg_worker_engine.connect() as conn:
            conn.execute(
                __import__("sqlalchemy").text(
                    "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, claimed_at, claimed_by, claim_token, attempts, suspect) "
                    "VALUES (777, 1, 'input_write', now() - interval '1 hour', 'test-worker', :token, 0, false)"
                ),
                {"token": str(token)},
            )
            conn.commit()

        held_tokens = {str(token)}
        thread = HeartbeatThread(worker_name="test-worker", interval=0.05, token_provider=lambda: held_tokens)
        thread.start()
        try:
            time.sleep(0.2)
        finally:
            thread.stop()
            thread.join(timeout=2)

        with pg_worker_engine.connect() as conn:
            row = conn.execute(
                __import__("sqlalchemy").text("SELECT claimed_at FROM ml_order_metrics_dirty WHERE order_id = 777")
            ).fetchone()
        claimed_at = row[0]
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        # Renewed to "now", not left an hour stale.
        assert (datetime.now(timezone.utc) - claimed_at).total_seconds() < 5.0


@pytest.mark.postgres
class TestHeartbeatDeathDetection:
    def test_is_healthy_false_once_thread_has_died(self, _worker_db_session) -> None:
        thread = HeartbeatThread(worker_name="test-worker", interval=0.05)
        thread.start()
        time.sleep(0.15)
        thread.stop()
        thread.join(timeout=2)
        assert thread.is_alive() is False
        assert thread.is_healthy() is False

    def test_is_healthy_false_when_no_tick_completed_for_three_intervals(self, _worker_db_session, monkeypatch) -> None:
        """A tick that raises every time never advances
        `_last_tick_completed_at` -- after `DEAD_AFTER_MISSED_INTERVALS *
        interval` with no successful tick, the thread reads as unhealthy
        even though `is_alive()` is still True (it keeps looping, just
        never succeeding)."""

        def _always_raise(self):
            raise RuntimeError("stubbed tick failure")

        monkeypatch.setattr(HeartbeatThread, "_tick", _always_raise)

        thread = HeartbeatThread(worker_name="test-worker", interval=0.02)
        thread.start()
        try:
            time.sleep(0.02 * 3 * 3)  # well past DEAD_AFTER_MISSED_INTERVALS * interval
            assert thread.is_alive() is True
            assert thread.is_healthy() is False
            assert isinstance(thread.last_tick_error, RuntimeError)
        finally:
            thread.stop()
            thread.join(timeout=2)

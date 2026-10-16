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

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.workers.heartbeat import HeartbeatThread

# Ticks the heartbeat must complete on its own while the main thread is blocked.
TICKS = 3
# Generous ceiling for the handshake: a slow CI runner only makes the test slower, never red.
WAIT_SECONDS = 30


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
        self, _worker_db_session, pg_worker_engine, monkeypatch
    ) -> None:
        """Handshake, not sleeps: the main thread blocks on an Event until the
        heartbeat thread has COMPLETED `TICKS` ticks on its own, and the
        thread is then frozen at the start of the next tick, so nothing moves
        while it is inspected. Health is read on an explicit clock (when the
        main loop would next look, one interval after the last completed
        tick), never on how long a tick took on a loaded machine."""
        real_tick = HeartbeatThread._tick
        tick_started_at: list[datetime] = []
        ticks_done = threading.Event()
        release = threading.Event()

        def counted_tick(self) -> None:
            if len(tick_started_at) == TICKS:
                # Entering tick TICKS+1: run() has already recorded tick TICKS as completed.
                ticks_done.set()
                release.wait(timeout=WAIT_SECONDS)
            tick_started_at.append(datetime.now(timezone.utc))
            real_tick(self)

        monkeypatch.setattr(HeartbeatThread, "_tick", counted_tick)
        thread = HeartbeatThread(worker_name="test-worker", interval=0.05)
        thread.start()
        try:
            # The main thread stuck inside a long handler call -- the heartbeat must keep ticking on its own.
            assert ticks_done.wait(timeout=WAIT_SECONDS), "the heartbeat thread stopped ticking"
            assert thread.is_alive() is True
            assert thread.last_tick_error is None
            last_tick = thread._last_tick_completed_at
            assert last_tick is not None
            assert thread.is_healthy(now=last_tick + timedelta(seconds=thread.interval)) is True

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
            # Written by the LAST completed tick, i.e. it advanced past every earlier one.
            assert tick_started_at[0] < tick_started_at[-1] <= heartbeat_at <= last_tick
        finally:
            release.set()
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

"""RED/GREEN -- `order_metrics.drain` (ventas-ml-rediseno PR3.T6-T9, design
D5/D6): claim -> bulk COMPUTE -> per-order fenced STORE, batch-timeout
suspect release + singleton retry, held-token registration with the
runtime's heartbeat hook, and registration in the generic worker registry.

Real Postgres: `ml_order_metrics_dirty`'s `FOR UPDATE SKIP LOCKED` claim and
the claim-token fence are Postgres-only statements.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers.context import WorkerContext
from app.workers.handlers.order_metrics import drain
from app.workers.heartbeat import HeartbeatThread
from app.workers.registry import REGISTRY


def _insert_order(conn, order_id: int, **overrides) -> None:
    row = {
        "order_id": order_id,
        "seller_id": 999,
        "status": overrides.get("status", "paid"),
    }
    conn.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
            "VALUES (:order_id, :seller_id, :status, now(), now()) ON CONFLICT (order_id) DO NOTHING"
        ),
        row,
    )


def _insert_dirty(conn, order_id: int, **overrides) -> None:
    row = {
        "order_id": order_id,
        "version": 1,
        "reason": "input_write",
        "claimed_at": None,
        "claimed_by": None,
        "claim_token": None,
        "attempts": 0,
        "last_error": None,
        "suspect": False,
    }
    row.update(overrides)
    conn.execute(
        text(
            "INSERT INTO ml_order_metrics_dirty "
            "(order_id, version, reason, claimed_at, claimed_by, claim_token, attempts, last_error, suspect) "
            "VALUES (:order_id, :version, :reason, :claimed_at, :claimed_by, :claim_token, :attempts, :last_error, :suspect)"
        ),
        row,
    )


@pytest.fixture()
def _order_metrics_db_session(monkeypatch, pg_order_metrics_engine):
    session_factory = sessionmaker(bind=pg_order_metrics_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    yield
    with pg_order_metrics_engine.connect() as conn:
        conn.execute(text("DELETE FROM ml_venta_deducciones"))
        conn.execute(text("DELETE FROM ml_order_metrics"))
        conn.execute(text("DELETE FROM ml_order_metrics_dirty"))
        conn.execute(text("DELETE FROM ml_orders_ops"))
        conn.commit()


def _far_deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=30)


@pytest.mark.postgres
class TestDrainRegisteredInGenericRegistry:
    """PR3.T7: registered in `registry.py` with the right channel."""

    def test_drain_is_registered_with_order_metrics_dirty_channel(self) -> None:
        names = {h.name: h for h in REGISTRY}
        assert "order_metrics.drain" in names
        assert names["order_metrics.drain"].channels == ("order_metrics_dirty",)
        assert names["order_metrics.drain"].interval is None
        assert names["order_metrics.drain"].run_at_local is None


@pytest.mark.postgres
class TestDrainClaimComputeStore:
    """PR3.T6/T8: a manually inserted dirty row is claimed, recomputed, and
    deleted from the queue within one drain pass (no triggers needed)."""

    def test_single_dirty_order_is_recomputed_and_removed_from_queue(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        order_id = 500001
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, order_id)
            _insert_dirty(conn, order_id)
            conn.commit()

        ctx = WorkerContext(deadline=_far_deadline(), worker_name="w", held_tokens=set())
        result = drain.run(ctx)

        assert result.success is True
        assert result.detail["processed"] == 1
        with pg_order_metrics_engine.connect() as conn:
            dirty = conn.execute(
                text("SELECT 1 FROM ml_order_metrics_dirty WHERE order_id = :oid"), {"oid": order_id}
            ).fetchone()
            metrics = conn.execute(
                text("SELECT 1 FROM ml_order_metrics WHERE order_id = :oid"), {"oid": order_id}
            ).fetchone()
        assert dirty is None
        assert metrics is not None
        assert ctx.held_tokens == set()  # every token released after the pass

    def test_multiple_dirty_orders_all_drained_in_one_pass(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        order_ids = [500010, 500011, 500012]
        with pg_order_metrics_engine.connect() as conn:
            for order_id in order_ids:
                _insert_order(conn, order_id)
                _insert_dirty(conn, order_id)
            conn.commit()

        ctx = WorkerContext(deadline=_far_deadline(), worker_name="w")
        result = drain.run(ctx)

        assert result.detail["processed"] == 3
        with pg_order_metrics_engine.connect() as conn:
            remaining = conn.execute(text("SELECT count(*) FROM ml_order_metrics_dirty")).scalar()
        assert remaining == 0

    def test_empty_queue_processes_nothing(self, _order_metrics_db_session) -> None:
        ctx = WorkerContext(deadline=_far_deadline(), worker_name="w")
        result = drain.run(ctx)
        assert result.detail["processed"] == 0
        assert result.detail["batches"] == 0


@pytest.mark.postgres
class TestDrainBatchTimeoutSuspectRetry:
    """PR3.T6d/T6e (simplified, single-process): a batch whose COMPUTE
    phase exceeds `batch_timeout` releases every claim uncharged and
    `suspect`, with zero attempts charged; the next pass retries each order
    ALONE (singleton pass) and succeeds normally."""

    def test_batch_timeout_releases_uncharged_and_suspect_then_singleton_retry_succeeds(
        self, monkeypatch, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        order_ids = [500020, 500021]
        with pg_order_metrics_engine.connect() as conn:
            for order_id in order_ids:
                _insert_order(conn, order_id)
                _insert_dirty(conn, order_id)
            conn.commit()

        # The multi-order batch always exceeds its budget; a SINGLETON
        # retry (batch of one) does not -- isolates the effect to exactly
        # one BatchTimeout, the multi-order batch's own.
        import app.workers.handlers.order_metrics as handler_module

        real_compute_batch = handler_module._compute_batch

        def _flaky_compute_batch(claims, batch_deadline):
            if len(claims) > 1:
                raise handler_module.BatchTimeout("simulated multi-order batch timeout")
            return real_compute_batch(claims, batch_deadline)

        monkeypatch.setattr(handler_module, "_compute_batch", _flaky_compute_batch)

        ctx = WorkerContext(deadline=_far_deadline(), worker_name="w")
        result = drain.run(ctx)

        # The initial 2-order batch always exceeds its budget -> released
        # uncharged and suspect (proven by never being charged an attempt),
        # then each order is retried ALONE (singleton pass, batch of one)
        # where the budget is no longer exceeded, and both succeed --
        # zero attempts charged to either order throughout.
        assert result.detail["processed"] == 2
        with pg_order_metrics_engine.connect() as conn:
            remaining = conn.execute(text("SELECT count(*) FROM ml_order_metrics_dirty")).scalar()
            metrics_rows = conn.execute(
                text("SELECT order_id FROM ml_order_metrics WHERE order_id = ANY(:ids)"), {"ids": order_ids}
            ).fetchall()
        assert remaining == 0
        assert {r.order_id for r in metrics_rows} == set(order_ids)


@pytest.mark.postgres
class TestDrainPerOrderFailureIsolation:
    """PR3.T4e/T6 (per-order store isolation): a store-phase exception for
    ONE order is charged only to that order; the rest of the batch still
    succeeds."""

    def test_one_bad_order_does_not_block_the_rest_of_the_batch(
        self, monkeypatch, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        good_ids = [500030, 500031]
        bad_id = 500032
        with pg_order_metrics_engine.connect() as conn:
            for order_id in good_ids + [bad_id]:
                _insert_order(conn, order_id)
                _insert_dirty(conn, order_id)
            conn.commit()

        import app.workers.handlers.order_metrics as handler_module

        real_fenced_store = handler_module.fenced_store

        def _flaky_fenced_store(claims, metrics):
            if claims and claims[0].order_id == bad_id:
                raise RuntimeError("simulated per-order store failure")
            return real_fenced_store(claims, metrics)

        monkeypatch.setattr(handler_module, "fenced_store", _flaky_fenced_store)

        ctx = WorkerContext(deadline=_far_deadline(), worker_name="w")
        result = drain.run(ctx)

        # The two good orders succeed in the first batch; the bad order
        # keeps failing alone (singleton pass) on every subsequent pass of
        # this same drain.run() call until it parks at POISON_THRESHOLD --
        # proving its repeated failure never blocks the good orders, which
        # were already stored on the very first pass.
        assert result.detail["processed"] == 2  # the two good orders

        with pg_order_metrics_engine.connect() as conn:
            bad_row = conn.execute(
                text("SELECT attempts, last_error FROM ml_order_metrics_dirty WHERE order_id = :oid"), {"oid": bad_id}
            ).fetchone()
            good_remaining = conn.execute(
                text("SELECT count(*) FROM ml_order_metrics_dirty WHERE order_id = ANY(:ids)"), {"ids": good_ids}
            ).scalar()
        assert bad_row.attempts == 5  # parked, isolated to itself
        assert "simulated per-order store failure" in bad_row.last_error
        assert good_remaining == 0


@pytest.mark.postgres
class TestDrainHeldTokenRegistration:
    """PR3.T6a: the claim token is registered in `ctx.held_tokens` for the
    duration of the claim, and removed once stored/released -- the same set
    object the runtime feeds `HeartbeatThread.token_provider`."""

    def test_token_present_during_store_and_absent_after(
        self, monkeypatch, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        order_id = 500040
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, order_id)
            _insert_dirty(conn, order_id)
            conn.commit()

        import app.workers.handlers.order_metrics as handler_module

        real_fenced_store = handler_module.fenced_store
        observed_tokens_during_store: list = []

        def _observing_fenced_store(claims, metrics):
            observed_tokens_during_store.append(set(ctx.held_tokens))
            return real_fenced_store(claims, metrics)

        ctx = WorkerContext(deadline=_far_deadline(), worker_name="w", held_tokens=set())
        monkeypatch.setattr(handler_module, "fenced_store", _observing_fenced_store)

        drain.run(ctx)

        assert len(observed_tokens_during_store) == 1
        assert len(observed_tokens_during_store[0]) == 1  # the one held token, present during the store call
        assert ctx.held_tokens == set()  # released once the pass finishes


@pytest.mark.postgres
class TestStorePhaseDoesNotBlockConcurrentWriterOrHeartbeat:
    """PR3.T6f (design D5 rev 6): while a batch's STORE phase is holding
    ONE order's short transaction open, (a) a concurrent input writer
    upserting a DIFFERENT order's dirty row (not yet stored) completes
    without waiting for the rest of the batch, and (b) every heartbeat
    lease-renewal tick during that window succeeds. Real Postgres, two real
    sessions, threading -- the whole reason the STORE phase is one short
    transaction PER order instead of one batch-wide transaction is exactly
    this; an assertion that never actually contends proves nothing."""

    def test_writer_and_heartbeat_stay_unblocked_during_store_phase(
        self, monkeypatch, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        import threading
        import time

        import app.services.order_metrics.queue as queue_module
        from app.models.worker_job_state import WorkerJobState

        # `HeartbeatThread` also upserts `worker_job_state` on every tick
        # (design D4 step 5); `pg_order_metrics_engine` does not create it
        # (order_metrics's own tables never needed it before this test).
        # `checkfirst=True` on both ends -- deliberately per-Table, never
        # `Base.metadata.create_all`/`drop_all` (PR2 known footgun: it walks
        # the whole shared metadata for enum-drop ordering and collides with
        # another module-scoped fixture's own types).
        WorkerJobState.__table__.create(bind=pg_order_metrics_engine, checkfirst=True)

        order_ids = [800001, 800002, 800003, 800004, 800005]
        blocked_order_id = order_ids[0]
        writer_order_id = order_ids[-1]  # last in claim order -- not yet stored while the first is blocked

        with pg_order_metrics_engine.connect() as conn:
            for order_id in order_ids:
                _insert_order(conn, order_id)
                _insert_dirty(conn, order_id)
            conn.commit()

        store_phase_entered = threading.Event()
        release_store_phase = threading.Event()
        real_store_order_metrics = queue_module.store_order_metrics

        def _blocking_store_order_metrics(session, metrics_by_order):
            (order_id,) = metrics_by_order.keys()
            if order_id == blocked_order_id:
                store_phase_entered.set()
                # Bounded wait -- never hangs the test suite even if the
                # release signal is somehow never sent.
                released = release_store_phase.wait(timeout=10)
                if not released:
                    raise AssertionError("release_store_phase was never signalled -- test harness bug")
            return real_store_order_metrics(session, metrics_by_order)

        monkeypatch.setattr(queue_module, "store_order_metrics", _blocking_store_order_metrics)

        ctx = WorkerContext(deadline=_far_deadline(), worker_name="t6f-worker", held_tokens=set())

        heartbeat = HeartbeatThread(
            worker_name="t6f-worker",
            interval=0.15,
            token_provider=lambda: set(ctx.held_tokens or set()),
        )
        heartbeat.start()

        drain_thread = threading.Thread(target=drain.run, args=(ctx,))
        drain_thread.start()

        try:
            entered_in_time = store_phase_entered.wait(timeout=10)
            assert entered_in_time, "STORE phase for the blocked order never started"

            # (a) the concurrent input writer -- upserting the dirty row of
            # an order NOT YET stored -- must complete fast, NOT waiting
            # behind the blocked order's still-open per-order transaction.
            writer_started_at = time.monotonic()
            with pg_order_metrics_engine.connect() as writer_conn:
                writer_conn.execute(
                    text(
                        "UPDATE ml_order_metrics_dirty SET version = version + 1, reason = 'input_write' "
                        "WHERE order_id = :order_id"
                    ),
                    {"order_id": writer_order_id},
                )
                writer_conn.commit()
            writer_elapsed = time.monotonic() - writer_started_at

            # (b) let a few heartbeat ticks land while the STORE phase is
            # still blocked, then confirm every one of them succeeded (lease
            # renewal is part of that same tick -- design D4 step 5).
            time.sleep(0.6)
            assert heartbeat.last_tick_error is None
            assert heartbeat.is_healthy()

            release_store_phase.set()
        finally:
            drain_thread.join(timeout=15)
            heartbeat.stop()
            heartbeat.join(timeout=5)

        assert not drain_thread.is_alive()
        # The writer's own upsert never contended with the blocked order's
        # open transaction -- it is a DIFFERENT row (Postgres row-level
        # locking), so it must finish in a small fraction of the ~10s the
        # blocked store COULD have held the lock for.
        assert writer_elapsed < 2.0, f"writer waited {writer_elapsed:.2f}s -- STORE phase blocked an unrelated row"
        assert heartbeat.last_tick_error is None

        with pg_order_metrics_engine.connect() as conn:
            blocked_row = conn.execute(
                text("SELECT 1 FROM ml_order_metrics_dirty WHERE order_id = :oid"), {"oid": blocked_order_id}
            ).fetchone()
            other_rows = conn.execute(
                text("SELECT count(*) FROM ml_order_metrics_dirty WHERE order_id = ANY(:ids)"),
                {"ids": [oid for oid in order_ids if oid not in (blocked_order_id, writer_order_id)]},
            ).scalar()
        # The blocked order was eventually stored and removed from the queue.
        assert blocked_row is None
        # Every order untouched by the concurrent writer was stored and
        # removed too -- the writer's row-level write never widened its
        # blast radius to the rest of the batch.
        assert other_rows == 0

        with pg_order_metrics_engine.connect() as conn:
            conn.execute(text("DELETE FROM worker_job_state WHERE name = 't6f-worker'"))
            conn.commit()


@pytest.mark.postgres
class TestOrderWithoutComputableMetricsDoesNotLivelock:
    """Review finding R3-001: when the bulk COMPUTE returns nothing for a
    claimed order (an order with no `ml_orders_ops` row is the reachable
    case), releasing it uncharged put it back at `attempts = 0`, not
    suspect -- so the very next `claim_dirty` of the SAME `run()` loop
    claimed it again at once. Nothing ever failed, nothing ever parked, and
    the pass spun claim/compute/release against the database until its
    deadline, on every drain. The order must be CHARGED instead, so it
    parks like any other order that cannot make progress."""

    def test_uncomputable_order_is_charged_and_the_pass_terminates(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        order_id = 500900
        with pg_order_metrics_engine.connect() as conn:
            # Dirty row with NO matching ml_orders_ops row: compute returns
            # no metrics for it.
            _insert_dirty(conn, order_id)
            conn.commit()

        ctx = WorkerContext(
            deadline=datetime.now(timezone.utc) + timedelta(seconds=10),
            worker_name="w",
            held_tokens=set(),
        )
        started = datetime.now(timezone.utc)
        result = drain.run(ctx)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()

        assert result.success is True
        # Terminates on its own instead of spinning until the deadline.
        assert elapsed < 8, f"the pass spun until its deadline ({elapsed:.1f}s)"
        with pg_order_metrics_engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM ml_order_metrics_dirty WHERE order_id = :oid"),
                {"oid": order_id},
            ).fetchone()
        assert row is not None, "the order must stay queued, not vanish"
        assert row.attempts >= 1, "an order that cannot be computed must be charged, or it is re-claimed forever"
        assert ctx.held_tokens == set()


@pytest.mark.postgres
class TestHeldTokensAreAlwaysReleased:
    """Review finding R4-001: `run()` registered the batch's claim tokens
    with the heartbeat and relied on every path inside the batch to
    unregister them. If a RECOVERY call itself raised -- `mark_failed` or
    `release_uncharged` hitting a connection reset, a failover or a
    PgBouncer restart -- the exception escaped and the tokens stayed in the
    shared set. The heartbeat then renewed those leases for the life of the
    process, so the rows never aged into the lease-expiry charge and never
    became claimable again (`claim_dirty` only takes rows with
    `claimed_at IS NULL`): those orders were stuck for good. The tokens must
    be released whatever happens."""

    def test_tokens_are_released_even_when_the_recovery_call_raises(
        self, _order_metrics_db_session, pg_order_metrics_engine, monkeypatch
    ) -> None:
        order_id = 500910
        with pg_order_metrics_engine.connect() as conn:
            _insert_dirty(conn, order_id)  # no ml_orders_ops row -> no_metrics path
            conn.commit()

        def _exploding_mark_failed(*args, **kwargs):
            raise RuntimeError("connection reset by peer")

        monkeypatch.setattr("app.workers.handlers.order_metrics.mark_failed", _exploding_mark_failed)

        ctx = WorkerContext(deadline=_far_deadline(), worker_name="w", held_tokens=set())
        with pytest.raises(RuntimeError):
            drain.run(ctx)

        assert ctx.held_tokens == set(), (
            "a claim token left in the set is renewed forever by the heartbeat: that order is unrecoverable"
        )

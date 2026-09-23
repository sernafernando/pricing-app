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

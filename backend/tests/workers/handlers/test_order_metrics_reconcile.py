"""RED/GREEN -- `order_metrics.reconcile` (ventas-ml-rediseno PR6.T1/T1a/T2,
design D10): every-10-minutes handler, batches of 5000, set-based
`INSERT...SELECT` via `order_metrics_enqueue_system` (never
`order_metrics_enqueue` -- must not un-park), enqueuing orders with no
metrics row OR `formula_version < CURRENT_FORMULA_VERSION` that have no
dirty row yet.

Real Postgres: `order_metrics_enqueue_system` and `FOR UPDATE SKIP LOCKED`
claim/store round trips are Postgres-only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.order_metrics.queue import POISON_THRESHOLD, claim_dirty, fenced_store
from app.workers.context import WorkerContext
from app.workers.handlers.order_metrics import reconcile
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


def _insert_metrics(conn, order_id: int, *, formula_version: int) -> None:
    conn.execute(
        text(
            "INSERT INTO ml_order_metrics "
            "(order_id, neto, neto_sin_iva, iva_reconcilia, costo_mercaderia, total_gauss, markup_pct, "
            " gauss_status, provisional_falta, unresolved_reason, formula_version, computed_at) "
            "VALUES (:order_id, 100, 82.64, true, 50, 40, 80, 'ok', NULL, NULL, :formula_version, now())"
        ),
        {"order_id": order_id, "formula_version": formula_version},
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


def _dirty_row(conn, order_id: int):
    return conn.execute(
        text("SELECT * FROM ml_order_metrics_dirty WHERE order_id = :order_id"), {"order_id": order_id}
    ).fetchone()


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
class TestReconcileRegisteredInRegistry:
    def test_registered_with_ten_minute_interval(self) -> None:
        names = {h.name: h for h in REGISTRY}
        assert "order_metrics.reconcile" in names
        handler = names["order_metrics.reconcile"]
        assert handler.interval == timedelta(minutes=10)
        assert handler.run_at_local is None
        # Schedule-only: never woken by a channel notify (design D6).
        assert handler.channels == ()


@pytest.mark.postgres
class TestReconcileEnqueuesMissingAndStaleFormula:
    def test_enqueues_order_with_no_metrics_row(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 500001)
            conn.commit()

        result = reconcile.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))
        assert result.success is True

        with pg_order_metrics_engine.connect() as conn:
            row = _dirty_row(conn, 500001)
        assert row is not None
        assert row.reason == "reconcile"

    def test_enqueues_order_with_stale_formula_version(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 500002)
            _insert_metrics(conn, 500002, formula_version=CURRENT_FORMULA_VERSION - 1)
            conn.commit()

        reconcile.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        with pg_order_metrics_engine.connect() as conn:
            row = _dirty_row(conn, 500002)
        assert row is not None
        assert row.reason == "reconcile"

    def test_does_not_enqueue_order_with_current_formula_version(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 500003)
            _insert_metrics(conn, 500003, formula_version=CURRENT_FORMULA_VERSION)
            conn.commit()

        reconcile.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        with pg_order_metrics_engine.connect() as conn:
            row = _dirty_row(conn, 500003)
        assert row is None

    def test_never_resets_attempts_of_an_existing_dirty_row(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        """The system enqueue is ON CONFLICT DO NOTHING (PR4) -- reconcile
        must call it, never `order_metrics_enqueue`, so an already-dirty row
        (any state) is left completely alone."""
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 500004)
            _insert_dirty(conn, 500004, attempts=3, last_error="previous failure", version=9)
            conn.commit()

        reconcile.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        with pg_order_metrics_engine.connect() as conn:
            row = _dirty_row(conn, 500004)
        assert row.attempts == 3
        assert row.last_error == "previous failure"
        assert row.version == 9


@pytest.mark.postgres
class TestReconcileParkedOrderStaysParkedAcrossRuns:
    """PR6.T1a (design D3, D10; spec scenario 13): a parked order with no
    metrics row survives three consecutive reconcile runs still parked; a
    subsequent real input write un-parks it and the next drain recomputes
    it."""

    def test_parked_order_survives_three_reconcile_runs(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        order_id = 500005
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, order_id)
            _insert_dirty(conn, order_id, attempts=POISON_THRESHOLD, last_error="boom")
            conn.commit()

        for _ in range(3):
            reconcile.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))
            with pg_order_metrics_engine.connect() as conn:
                row = _dirty_row(conn, order_id)
            assert row.attempts == POISON_THRESHOLD
            assert row.last_error == "boom"

        # A real input write (the input-conflict enqueue, `attempts=0`
        # reset, `suspect=false`) un-parks it (design D3).
        with pg_order_metrics_engine.connect() as conn:
            conn.execute(
                text("SELECT order_metrics_enqueue(ARRAY[:order_id]::bigint[], 'input_write')"),
                {"order_id": order_id},
            )
            conn.commit()
            row = _dirty_row(conn, order_id)
        assert row.attempts == 0
        assert row.last_error is None

        # The next drain claims and recomputes it normally.
        claims = claim_dirty(limit=10, lease=timedelta(seconds=60), worker_id="w")
        [claim] = [c for c in claims if c.order_id == order_id]
        compute_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        compute_session = compute_session_factory()
        try:
            metrics = compute_order_metrics(compute_session, [order_id])
        finally:
            compute_session.close()
        result = fenced_store([claim], metrics)
        assert order_id in result.stored_order_ids or order_id in result.unclaimed_order_ids

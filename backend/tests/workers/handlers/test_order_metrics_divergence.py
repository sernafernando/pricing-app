"""RED/GREEN -- `order_metrics.divergence` (ventas-ml-rediseno PR6.T3/T4/T5,
design D10): daily (04:00 AR) handler, batches of 500, compares every
stored field + status + formula_version vs a fresh `compute_order_metrics`,
skipping orders currently dirty; writes a JSON summary to
`worker_job_state.detail`, opens `ml_ops_divergence` rows
(`kind='stored_metrics_mismatch'`) for the first N divergent ids, and
re-enqueues divergent orders via the system enqueue (self-heal).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers.context import WorkerContext
from app.workers.handlers import order_metrics as order_metrics_handlers
from app.workers.handlers.order_metrics import divergence
from app.workers.registry import REGISTRY


def _insert_order(conn, order_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
            "VALUES (:order_id, 999, 'paid', now(), now()) ON CONFLICT (order_id) DO NOTHING"
        ),
        {"order_id": order_id},
    )


def _insert_metrics(conn, order_id: int, *, total_gauss: str = "40.00", formula_version: int = 2) -> None:
    conn.execute(
        text(
            "INSERT INTO ml_order_metrics "
            "(order_id, neto, neto_sin_iva, iva_reconcilia, costo_mercaderia, total_gauss, markup_pct, "
            " gauss_status, provisional_falta, unresolved_reason, formula_version, computed_at) "
            "VALUES (:order_id, 100, 82.64, true, 50, :total_gauss, 80, 'ok', NULL, NULL, :formula_version, now())"
        ),
        {"order_id": order_id, "total_gauss": total_gauss, "formula_version": formula_version},
    )


def _insert_dirty(conn, order_id: int) -> None:
    conn.execute(
        text("INSERT INTO ml_order_metrics_dirty (order_id, version, reason) VALUES (:order_id, 1, 'input_write')"),
        {"order_id": order_id},
    )


@pytest.fixture()
def _order_metrics_db_session(monkeypatch, pg_order_metrics_divergence_engine):
    session_factory = sessionmaker(bind=pg_order_metrics_divergence_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    yield
    with pg_order_metrics_divergence_engine.connect() as conn:
        conn.execute(text("DELETE FROM ml_venta_deducciones"))
        conn.execute(text("DELETE FROM ml_ops_divergence"))
        conn.execute(text("DELETE FROM worker_job_state"))
        conn.execute(text("DELETE FROM ml_order_metrics"))
        conn.execute(text("DELETE FROM ml_order_metrics_dirty"))
        conn.execute(text("DELETE FROM ml_orders_ops"))
        conn.commit()


def _far_deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=30)


@pytest.mark.postgres
class TestDivergenceRegisteredInRegistry:
    def test_registered_with_daily_slot(self) -> None:
        names = {h.name: h for h in REGISTRY}
        assert "order_metrics.divergence" in names
        handler = names["order_metrics.divergence"]
        assert handler.run_at_local == time(4, 0)
        assert handler.interval is None
        assert handler.channels == ()


@pytest.mark.postgres
class TestDivergenceDetectsInjectedMismatch:
    def test_stale_stored_value_opens_divergence_and_reenqueues(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        order_id = 600001
        with pg_order_metrics_divergence_engine.connect() as conn:
            _insert_order(conn, order_id)
            # Injected mismatch: stored total_gauss disagrees with what a
            # fresh recompute against ml_orders_ops-derived data produces.
            _insert_metrics(conn, order_id, total_gauss="999999.00")
            conn.commit()

        result = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))
        assert result.success is True
        assert result.detail["divergent_count"] >= 1

        with pg_order_metrics_divergence_engine.connect() as conn:
            div_row = conn.execute(
                text(
                    "SELECT kind, state FROM ml_ops_divergence WHERE order_id = :order_id "
                    "AND kind = 'stored_metrics_mismatch'"
                ),
                {"order_id": order_id},
            ).fetchone()
            dirty_row = conn.execute(
                text("SELECT reason FROM ml_order_metrics_dirty WHERE order_id = :order_id"), {"order_id": order_id}
            ).fetchone()

        assert div_row is not None
        assert div_row.state == "open"
        assert dirty_row is not None
        assert dirty_row.reason == "divergence"

    def test_matching_stored_value_opens_nothing(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        order_id = 600002
        with pg_order_metrics_divergence_engine.connect() as conn:
            _insert_order(conn, order_id)
            conn.commit()

        # First, compute what SHOULD be stored via a real recompute, then
        # store exactly that -- divergence must find zero mismatch.
        from app.services.order_metrics.store import recompute_order_metrics

        session_factory = sessionmaker(bind=pg_order_metrics_divergence_engine)
        session = session_factory()
        try:
            recompute_order_metrics(session, [order_id])
            session.commit()
        finally:
            session.close()

        result = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))
        assert result.success is True

        with pg_order_metrics_divergence_engine.connect() as conn:
            div_row = conn.execute(
                text("SELECT id FROM ml_ops_divergence WHERE order_id = :order_id"), {"order_id": order_id}
            ).fetchone()
        assert div_row is None


@pytest.mark.postgres
class TestDivergenceSkipsCurrentlyDirtyOrders:
    def test_a_dirty_order_is_never_compared(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        order_id = 600003
        with pg_order_metrics_divergence_engine.connect() as conn:
            _insert_order(conn, order_id)
            _insert_metrics(conn, order_id, total_gauss="999999.00")  # would diverge if compared
            _insert_dirty(conn, order_id)
            conn.commit()

        divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        with pg_order_metrics_divergence_engine.connect() as conn:
            div_row = conn.execute(
                text("SELECT id FROM ml_ops_divergence WHERE order_id = :order_id"), {"order_id": order_id}
            ).fetchone()
        assert div_row is None  # never compared -- mid-flight, expected to differ


@pytest.mark.postgres
class TestDivergenceWritesSummaryToWorkerJobState:
    def test_summary_persisted_to_detail_json(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        order_id = 600004
        with pg_order_metrics_divergence_engine.connect() as conn:
            _insert_order(conn, order_id)
            conn.commit()

        from app.services.order_metrics.store import recompute_order_metrics

        session_factory = sessionmaker(bind=pg_order_metrics_divergence_engine)
        session = session_factory()
        try:
            recompute_order_metrics(session, [order_id])
            session.commit()
        finally:
            session.close()

        divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        with pg_order_metrics_divergence_engine.connect() as conn:
            row = conn.execute(
                text("SELECT detail FROM worker_job_state WHERE name = 'order_metrics.divergence'")
            ).fetchone()
        assert row is not None
        assert "divergent_count" in row.detail
        assert "missing_count" in row.detail
        assert "run_at" in row.detail


class _ScriptedNow:
    """Stand-in for `order_metrics.datetime` (module-level import) that
    returns a scripted sequence of `.now(tz)` results -- gives deterministic
    control over exactly when `ctx.deadline` is judged exceeded, instead of
    racing the wall clock against real DB round-trips."""

    def __init__(self, values):
        self._values = iter(values)

    def now(self, tz=None):  # noqa: ARG002 -- signature parity with datetime.now
        return next(self._values)


@pytest.mark.postgres
class TestDivergenceCompletionCursor:
    """PR6 review fix H1: a run truncated by `ctx.deadline` must NEVER claim
    it inspected the whole table. `complete=False` plus a persisted `cursor`
    is the only honest signal -- the production gate must not read
    `divergent_count=0` as clean when only the head of the table was ever
    looked at."""

    def test_deadline_truncated_pass_reports_incomplete(
        self, monkeypatch, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        monkeypatch.setattr(order_metrics_handlers, "DIVERGENCE_BATCH_SIZE", 1)
        order_ids = [600101, 600102, 600103]
        with pg_order_metrics_divergence_engine.connect() as conn:
            for order_id in order_ids:
                _insert_order(conn, order_id)
                _insert_metrics(conn, order_id)
            conn.commit()

        t0 = datetime.now(timezone.utc)
        deadline = t0 + timedelta(seconds=5)
        t_exceeded = deadline + timedelta(seconds=1)
        # started_at, loop-check#1 (enters, processes one batch of 1), loop-check#2 (exceeded, exits).
        monkeypatch.setattr(order_metrics_handlers, "datetime", _ScriptedNow([t0, t0, t_exceeded]))

        result = divergence.run(WorkerContext(deadline=deadline, worker_name="w"))

        assert result.success is True
        assert result.detail["complete"] is False
        assert result.detail["checked_count"] == 1
        assert result.detail["cursor"] == order_ids[0]

        with pg_order_metrics_divergence_engine.connect() as conn:
            row = conn.execute(
                text("SELECT detail FROM worker_job_state WHERE name = 'order_metrics.divergence'")
            ).fetchone()
        assert row.detail["complete"] is False

    def test_resumes_from_persisted_cursor_across_runs_until_complete(
        self, monkeypatch, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        monkeypatch.setattr(order_metrics_handlers, "DIVERGENCE_BATCH_SIZE", 1)
        order_ids = [600111, 600112, 600113]
        with pg_order_metrics_divergence_engine.connect() as conn:
            for order_id in order_ids:
                _insert_order(conn, order_id)
                _insert_metrics(conn, order_id)
            conn.commit()

        t0 = datetime.now(timezone.utc)
        deadline = t0 + timedelta(seconds=5)
        t_exceeded = deadline + timedelta(seconds=1)
        with monkeypatch.context() as scoped:
            scoped.setattr(order_metrics_handlers, "datetime", _ScriptedNow([t0, t0, t_exceeded]))
            first = divergence.run(WorkerContext(deadline=deadline, worker_name="w"))
        assert first.detail["complete"] is False
        assert first.detail["cursor"] == order_ids[0]

        # A second run with a real deadline (real `datetime` restored) and
        # `DIVERGENCE_BATCH_SIZE` still patched to 1, starting from the persisted
        # cursor, must reach the end of the table and finish the lap.
        second = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))
        assert second.detail["complete"] is True
        # Cumulative across both runs of the same lap, not just this run's slice.
        assert second.detail["checked_count"] == len(order_ids)


@pytest.mark.postgres
class TestDivergenceComparesAllPromisedFields:
    """PR6 review fix H2: `bool(x) != bool(y)` made `NULL` and `False`
    compare equal for `iva_reconcilia`, and `provisional_falta`/
    `unresolved_reason` were never selected nor compared at all."""

    def test_iva_reconcilia_null_vs_false_is_a_divergence(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        order_id = 600201
        with pg_order_metrics_divergence_engine.connect() as conn:
            _insert_order(conn, order_id)
            conn.commit()

        from app.services.order_metrics.store import recompute_order_metrics

        session_factory = sessionmaker(bind=pg_order_metrics_divergence_engine)
        session = session_factory()
        try:
            recompute_order_metrics(session, [order_id])
            session.commit()
        finally:
            session.close()

        with pg_order_metrics_divergence_engine.connect() as conn:
            fresh_row = conn.execute(
                text("SELECT iva_reconcilia FROM ml_order_metrics WHERE order_id = :order_id"), {"order_id": order_id}
            ).fetchone()
            # Force the stored value into the opposite of NULL/False that a
            # plain `bool(x) != bool(y)` comparison cannot tell apart.
            corrupted = None if fresh_row.iva_reconcilia is False else False
            conn.execute(
                text("UPDATE ml_order_metrics SET iva_reconcilia = :value WHERE order_id = :order_id"),
                {"value": corrupted, "order_id": order_id},
            )
            conn.commit()

        result = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))
        assert result.success is True

        with pg_order_metrics_divergence_engine.connect() as conn:
            div_row = conn.execute(
                text("SELECT id FROM ml_ops_divergence WHERE order_id = :order_id"), {"order_id": order_id}
            ).fetchone()
        assert div_row is not None

    def test_stale_unresolved_reason_is_a_divergence(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        order_id = 600202
        with pg_order_metrics_divergence_engine.connect() as conn:
            _insert_order(conn, order_id)
            conn.commit()

        from app.services.order_metrics.store import recompute_order_metrics

        session_factory = sessionmaker(bind=pg_order_metrics_divergence_engine)
        session = session_factory()
        try:
            recompute_order_metrics(session, [order_id])
            session.commit()
        finally:
            session.close()

        with pg_order_metrics_divergence_engine.connect() as conn:
            # A stale reason left behind that a fresh recompute would not
            # produce (the order was just successfully reconciled above).
            conn.execute(
                text("UPDATE ml_order_metrics SET unresolved_reason = 'sin_pagos' WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            conn.commit()

        result = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))
        assert result.success is True

        with pg_order_metrics_divergence_engine.connect() as conn:
            div_row = conn.execute(
                text("SELECT id FROM ml_ops_divergence WHERE order_id = :order_id"), {"order_id": order_id}
            ).fetchone()
        assert div_row is not None

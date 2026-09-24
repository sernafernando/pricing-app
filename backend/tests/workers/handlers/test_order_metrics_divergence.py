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

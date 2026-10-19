"""RED/GREEN -- `order_metrics.divergence` (ventas-ml-rediseno PR6.T3/T4/T5,
design D10): daily (04:00 AR) handler, batches of 500, compares every
stored field + status + formula_version vs a fresh `compute_order_metrics`,
skipping orders currently dirty; writes a JSON summary to
`worker_job_state.detail` and re-enqueues divergent orders via the system
enqueue (self-heal). It records no `ml_ops_divergence` row: the divergences
board is gone, the re-enqueue IS the fix.
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
        conn.execute(text("DELETE FROM ml_sale_lines"))
        conn.execute(text("DELETE FROM ml_group_metrics"))
        conn.execute(text("DELETE FROM ml_order_item_costos"))
        conn.execute(text("DELETE FROM ml_order_items_ops"))
        conn.execute(text("DELETE FROM ml_payments_ops"))
        conn.execute(text("DELETE FROM ml_order_metrics"))
        conn.execute(text("DELETE FROM ml_order_metrics_dirty"))
        conn.execute(text("DELETE FROM ml_orders_ops"))
        conn.commit()


def _queued_reason(engine, order_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT reason FROM ml_order_metrics_dirty WHERE order_id = :order_id"), {"order_id": order_id}
        ).fetchone()
    return row.reason if row is not None else None


def _divergence_rows(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM ml_ops_divergence")).scalar()


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

    def test_carries_a_catch_up_interval_for_continuous_lap_progress(self) -> None:
        """PR6 review fix J4: without a `catch_up_interval`,
        `scheduling.is_due` never unlocks the short cadence and the
        handler stays a plain once-a-day job -- 23+ hours idle per click
        of `POST /divergence/run` over a ~77k-order table."""
        names = {h.name: h for h in REGISTRY}
        handler = names["order_metrics.divergence"]
        assert handler.catch_up_interval == timedelta(minutes=2)


@pytest.mark.postgres
class TestDivergenceDetectsInjectedMismatch:
    def test_stale_stored_value_reenqueues_without_recording_a_row(
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

        assert _queued_reason(pg_order_metrics_divergence_engine, order_id) == "divergence"
        assert _divergence_rows(pg_order_metrics_divergence_engine) == 0

    def test_matching_stored_value_enqueues_nothing(
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
        assert result.detail["divergent_count"] == 0
        assert _queued_reason(pg_order_metrics_divergence_engine, order_id) is None


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

        result = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        # Never compared -- mid-flight, expected to differ.
        assert result.detail["divergent_count"] == 0
        assert _queued_reason(pg_order_metrics_divergence_engine, order_id) == "input_write"


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
        assert _queued_reason(pg_order_metrics_divergence_engine, order_id) == "divergence"

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
        assert _queued_reason(pg_order_metrics_divergence_engine, order_id) == "divergence"


@pytest.mark.postgres
class TestBumpDoesNotFloodDivergence:
    """ventas-ml-varios-base-envio: bumping `CURRENT_FORMULA_VERSION` makes
    EVERY stored row look stale to a fresh compute (`formula_version`
    differs). The recompute must not bury the divergence panel."""

    def _seed_stale(self, engine, first_id: int, count: int) -> list:
        from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION

        ids = list(range(first_id, first_id + count))
        with engine.connect() as conn:
            for order_id in ids:
                _insert_order(conn, order_id)
                _insert_metrics(conn, order_id, formula_version=CURRENT_FORMULA_VERSION - 1)
            conn.commit()
        return ids

    def test_once_reconcile_has_enqueued_the_backlog_divergence_compares_none_of_it(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        from app.workers.handlers.order_metrics import reconcile

        self._seed_stale(pg_order_metrics_divergence_engine, 700000, 150)
        reconcile.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        result = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        assert result.detail["divergent_count"] == 0
        assert result.detail["checked_count"] == 0

    def test_stale_rows_nobody_enqueued_yet_are_all_reenqueued_and_none_recorded(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        """The window between two reconcile runs: stale rows that are not
        dirty yet ARE compared and each is re-enqueued (it heals itself);
        nothing is written to `ml_ops_divergence`."""
        ids = self._seed_stale(pg_order_metrics_divergence_engine, 710000, 150)

        result = divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

        assert result.detail["divergent_count"] == 150
        with pg_order_metrics_divergence_engine.connect() as conn:
            requeued = conn.execute(
                text("SELECT count(*) FROM ml_order_metrics_dirty WHERE order_id = ANY(:ids)"), {"ids": ids}
            ).scalar()
        assert requeued == 150
        assert _divergence_rows(pg_order_metrics_divergence_engine) == 0


def _seed_sold_order(engine, order_id: int, *, pack_id=None) -> None:
    """An accredited order with one costed item, whose metrics and sale lines are
    stored by the real writer (so they match a live derivation)."""
    from app.services.order_metrics.store import recompute_order_metrics

    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_orders_ops (order_id, pack_id, seller_id, status, ml_last_updated, date_created) "
                "VALUES (:oid, :pack, 999, 'paid', now(), now())"
            ),
            {"oid": order_id, "pack": pack_id},
        )
        conn.execute(
            text(
                "INSERT INTO ml_order_items_ops (order_id, item_id, quantity, unit_price) VALUES (:oid, 'MLA600', 2, 100)"
            ),
            {"oid": order_id},
        )
        conn.execute(
            text(
                "INSERT INTO ml_order_item_costos (order_id, item_id, costo_origen, moneda, costo_unitario_ars, "
                "iva_pct, precio_unitario, fuente, producto_item_id) "
                "VALUES (:oid, 'MLA600', 60, 'ARS', 60, 21, 100, 'test', 4242)"
            ),
            {"oid": order_id},
        )
        conn.execute(
            text(
                "INSERT INTO ml_payments_ops (payment_id, order_id, status, date_approved) "
                "VALUES (:pid, :oid, 'approved', now())"
            ),
            {"pid": order_id * 10, "oid": order_id},
        )
        conn.commit()
    with sessionmaker(bind=engine)() as session:
        recompute_order_metrics(session, [order_id])
        session.commit()


@pytest.mark.postgres
class TestDivergenceChecksThePersistedSaleLines:
    """The self-heal of `ml_sale_lines`: the stored lines of an order's group are
    compared with a live derivation in the same lap, and a mismatch re-enqueues
    the group's orders (no divergence row is recorded)."""

    @pytest.fixture(autouse=True)
    def _seller(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ML_USER_ID", 999)

    def _run(self):
        return divergence.run(WorkerContext(deadline=_far_deadline(), worker_name="w"))

    def test_matching_lines_enqueue_nothing(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        _seed_sold_order(pg_order_metrics_divergence_engine, 610001)

        result = self._run()

        assert result.detail["lines_divergent_count"] == 0
        assert _queued_reason(pg_order_metrics_divergence_engine, 610001) is None

    @pytest.mark.parametrize(
        "damage",
        [
            "UPDATE ml_sale_lines SET qty = 99 WHERE order_id = 610002",
            "DELETE FROM ml_sale_lines WHERE order_id = 610002",
            "UPDATE ml_sale_lines SET tg = tg + 1 WHERE order_id = 610002",
            "UPDATE ml_order_item_costos SET producto_item_id = 4343 WHERE order_id = 610002",
        ],
        ids=["qty", "missing", "money", "product-changed-without-a-recompute"],
    )
    def test_a_mismatch_reenqueues_without_recording_a_row(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine, damage
    ) -> None:
        _seed_sold_order(pg_order_metrics_divergence_engine, 610002)
        with pg_order_metrics_divergence_engine.connect() as conn:
            conn.execute(text(damage))
            conn.commit()

        result = self._run()

        assert result.detail["lines_divergent_count"] == 1
        assert _queued_reason(pg_order_metrics_divergence_engine, 610002) == "divergence"
        assert _divergence_rows(pg_order_metrics_divergence_engine) == 0

    def test_a_group_with_an_order_in_the_queue_is_skipped(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        _seed_sold_order(pg_order_metrics_divergence_engine, 610003, pack_id=7100)
        _seed_sold_order(pg_order_metrics_divergence_engine, 610004, pack_id=7100)
        with pg_order_metrics_divergence_engine.connect() as conn:
            conn.execute(text("UPDATE ml_sale_lines SET qty = 99 WHERE order_id = 610003"))
            conn.execute(text("INSERT INTO ml_order_metrics_dirty (order_id, version, reason) VALUES (610004, 1, 'x')"))
            conn.commit()

        result = self._run()

        assert result.detail["lines_divergent_count"] == 0

    def test_every_order_of_the_group_is_reenqueued(
        self, _order_metrics_db_session, pg_order_metrics_divergence_engine
    ) -> None:
        _seed_sold_order(pg_order_metrics_divergence_engine, 610005, pack_id=7101)
        _seed_sold_order(pg_order_metrics_divergence_engine, 610006, pack_id=7101)
        with pg_order_metrics_divergence_engine.connect() as conn:
            conn.execute(text("UPDATE ml_sale_lines SET qty = 99 WHERE order_id = 610005"))
            conn.commit()

        self._run()

        for order_id in (610005, 610006):
            assert _queued_reason(pg_order_metrics_divergence_engine, order_id) is not None, order_id

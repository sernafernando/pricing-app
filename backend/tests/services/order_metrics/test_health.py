"""RED/GREEN -- `order_metrics.health` (ventas-ml-rediseno PR6.T6/T11a, design
D9/D10): read-only aggregates over `ml_order_metrics_dirty`/`ml_orders_ops`/
`ml_order_metrics` that back the `GET /order-metrics/health` endpoint. Real
Postgres: shares `pg_order_metrics_engine` with `test_queue.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.order_metrics.health import (
    claimed_count,
    missing_metrics_count,
    oldest_dirty_age_seconds,
    poisoned_orders,
    queue_depth,
)
from app.services.order_metrics.queue import POISON_THRESHOLD


def _insert_order(conn, order_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
            "VALUES (:order_id, 999, 'paid', now(), now()) ON CONFLICT (order_id) DO NOTHING"
        ),
        {"order_id": order_id},
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


@pytest.mark.postgres
class TestQueueDepthExcludesParkedAndClaimed:
    def test_only_counts_unclaimed_non_poisoned_rows(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            for order_id in (1, 2, 3):
                _insert_order(conn, order_id)
            _insert_dirty(conn, 1)
            _insert_dirty(conn, 2, attempts=POISON_THRESHOLD)
            _insert_dirty(conn, 3)
            conn.execute(text("UPDATE ml_order_metrics_dirty SET claimed_at = now() WHERE order_id = 3"))
            conn.commit()

        db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        db = db_session_factory()
        try:
            assert queue_depth(db) == 1
            assert claimed_count(db) == 1
        finally:
            db.close()


@pytest.mark.postgres
class TestOldestDirtyAge:
    def test_none_when_no_claimable_rows(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        db = db_session_factory()
        try:
            assert oldest_dirty_age_seconds(db) is None
        finally:
            db.close()

    def test_reports_age_of_the_oldest_claimable_row(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 10)
            conn.execute(
                text(
                    "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, enqueued_at) "
                    "VALUES (10, 1, 'input_write', now() - interval '90 seconds')"
                )
            )
            conn.commit()

        db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        db = db_session_factory()
        try:
            age = oldest_dirty_age_seconds(db)
            assert age is not None and age >= 89
        finally:
            db.close()

    def test_excludes_a_row_already_claimed_by_a_worker(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        """PR6 review fix H3: the docstring says this measures the oldest
        CLAIMABLE row, same as `queue_depth` -- but a claimed row was never
        filtered out. An operator watching a backfill wants to know how
        stale the still-WAITING queue is, not a row a worker already has a
        lease on."""
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 40)
            conn.execute(
                text(
                    "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, enqueued_at, claimed_at, claimed_by) "
                    "VALUES (40, 1, 'input_write', now() - interval '90 seconds', now(), 'some-worker')"
                )
            )
            conn.commit()

        db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        db = db_session_factory()
        try:
            assert oldest_dirty_age_seconds(db) is None
        finally:
            db.close()


@pytest.mark.postgres
class TestMissingMetricsCountExcludesParked:
    """PR6.T11a: a parked order (attempts >= 5, no metrics row) is NOT
    counted in missing_count, IS counted in poisoned_orders."""

    def test_parked_order_excluded_from_missing_count(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 20)  # no metrics row, no dirty row -> counts as missing
            _insert_order(conn, 21)  # no metrics row, parked dirty row -> excluded
            _insert_dirty(conn, 21, attempts=POISON_THRESHOLD, last_error="boom")
            conn.commit()

        db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        db = db_session_factory()
        try:
            assert missing_metrics_count(db) == 1

            poisoned = poisoned_orders(db)
            assert [(row.order_id, row.last_error) for row in poisoned] == [(21, "boom")]
        finally:
            db.close()

    def test_only_parked_orders_left_reads_zero_missing_nonzero_poisoned(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 30)
            _insert_dirty(conn, 30, attempts=POISON_THRESHOLD, last_error="bad data")
            conn.commit()

        db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        db = db_session_factory()
        try:
            assert missing_metrics_count(db) == 0
            assert len(poisoned_orders(db)) == 1
        finally:
            db.close()

"""RED/GREEN -- `claim_dirty` serves live work before bulk recomputes.

Seen in production (2026-10-07): a `CURRENT_FORMULA_VERSION` bump made
`order_metrics.reconcile` enqueue ~83k orders, and every sale ingested
afterwards waited behind all of them (FIFO by `enqueued_at`) for about an
hour. The claim now orders by tier (live first, bulk -- `reconcile` /
`divergence` -- after) and by `enqueued_at` inside each tier.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.database import get_background_db
from app.services.order_metrics.queue import BULK_REASONS, claim_dirty, enqueue_order_metrics

from tests.services.order_metrics.test_queue import _insert_order

_LEASE = timedelta(seconds=120)
_T0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def _priority_queue_db(monkeypatch, pg_order_metrics_engine):
    """Points `get_background_db()` at the Postgres test engine and empties
    the queue tables afterwards."""
    monkeypatch.setattr(
        "app.core.database.SessionLocal", sessionmaker(bind=pg_order_metrics_engine, autocommit=False, autoflush=False)
    )
    yield
    with pg_order_metrics_engine.connect() as conn:
        conn.execute(text("DELETE FROM ml_order_metrics_dirty"))
        conn.execute(text("DELETE FROM ml_orders_ops"))
        conn.commit()


def _seed(conn, order_id: int, reason: str, minutes: int, **overrides) -> None:
    """Dirty row `reason`, enqueued `minutes` after a fixed origin."""
    _insert_order(conn, order_id)
    row = {"order_id": order_id, "reason": reason, "enqueued_at": _T0 + timedelta(minutes=minutes), "attempts": 0}
    row.update(overrides)
    row.setdefault("suspect", False)
    conn.execute(
        text(
            "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, enqueued_at, attempts, suspect) "
            "VALUES (:order_id, 1, :reason, :enqueued_at, :attempts, :suspect)"
        ),
        row,
    )


def _claimed_ids(limit: int) -> List[int]:
    return [c.order_id for c in claim_dirty(limit=limit, lease=_LEASE, worker_id="w")]


@pytest.mark.postgres
@pytest.mark.usefixtures("_priority_queue_db")
class TestLiveWorkGoesFirst:
    def test_live_row_enqueued_after_the_whole_backlog_is_claimed_first(
        self,
        pg_order_metrics_engine,
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            for order_id in range(1, 11):
                _seed(conn, order_id, "reconcile", minutes=order_id)
            _seed(conn, 99, "ml_payments_ops_update", minutes=60)
            conn.commit()

        assert 99 in _claimed_ids(limit=3)

    def test_each_tier_stays_fifo_by_enqueued_at(self, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _seed(conn, 1, "reconcile", minutes=1)
            _seed(conn, 2, "ml_orders_ops_insert", minutes=30)
            _seed(conn, 3, "reconcile", minutes=2)
            _seed(conn, 4, "resync", minutes=20)
            conn.commit()

        assert _claimed_ids(limit=10) == [4, 2, 1, 3]

    def test_divergence_is_bulk_like_reconcile(self, pg_order_metrics_engine) -> None:
        assert BULK_REASONS == frozenset({"reconcile", "divergence"})
        with pg_order_metrics_engine.connect() as conn:
            _seed(conn, 1, "divergence", minutes=1)
            _seed(conn, 2, "configuracion_update", minutes=5)
            conn.commit()

        assert _claimed_ids(limit=1) == [2]

    def test_singleton_pass_also_prefers_live(self, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _seed(conn, 1, "reconcile", minutes=1, attempts=1)
            _seed(conn, 2, "ml_payments_ops_update", minutes=9, suspect=True)
            conn.commit()

        assert _claimed_ids(limit=10) == [2]


@pytest.mark.postgres
@pytest.mark.usefixtures("_priority_queue_db")
class TestPromotionOfAQueuedBulkRow:
    def test_live_enqueue_over_a_reconcile_row_promotes_it(
        self,
        pg_order_metrics_engine,
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            for order_id in range(1, 6):
                _seed(conn, order_id, "reconcile", minutes=order_id)
            conn.commit()

        with get_background_db() as session:
            enqueue_order_metrics(session, [5], "ml_payments_ops_update")
            session.commit()

        with pg_order_metrics_engine.connect() as conn:
            reason = conn.execute(text("SELECT reason FROM ml_order_metrics_dirty WHERE order_id = 5")).scalar()
        assert reason == "ml_payments_ops_update"
        assert _claimed_ids(limit=1) == [5]

    def test_system_enqueue_never_downgrades_a_live_row(
        self,
        pg_order_metrics_engine,
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _seed(conn, 7, "ml_payments_ops_update", minutes=1)
            conn.execute(text("SELECT order_metrics_enqueue_system(ARRAY[7]::bigint[], 'reconcile')"))
            conn.commit()
            reason = conn.execute(text("SELECT reason FROM ml_order_metrics_dirty WHERE order_id = 7")).scalar()
        assert reason == "ml_payments_ops_update"


@pytest.mark.postgres
@pytest.mark.usefixtures("_priority_queue_db")
class TestClaimUsesThePriorityIndex:
    """Without `ix_ml_order_metrics_dirty_priority` the ORDER BY sorts the
    whole queue on every claim (45 ms and a disk spill with 80k rows)."""

    @pytest.mark.parametrize("pass_name", ["batch", "singleton"])
    def test_claim_order_by_is_an_index_scan_not_a_sort(
        self,
        pg_order_metrics_engine,
        pass_name,
    ) -> None:
        from app.services.order_metrics import queue

        where = (
            "claimed_at IS NULL AND attempts = 0 AND NOT suspect"
            if pass_name == "batch"
            else "claimed_at IS NULL AND attempts < 5 AND (attempts > 0 OR suspect)"
        )
        with pg_order_metrics_engine.connect() as conn:
            conn.execute(text("SET enable_seqscan = off"))
            plan = "\n".join(
                row[0]
                for row in conn.execute(
                    text(
                        f"EXPLAIN SELECT order_id FROM ml_order_metrics_dirty WHERE {where} "
                        f"ORDER BY {queue._TIER_SQL}, enqueued_at LIMIT 200 FOR UPDATE SKIP LOCKED"
                    )
                )
            )
        assert "ix_ml_order_metrics_dirty_priority" in plan, plan
        assert "Sort" not in plan, plan

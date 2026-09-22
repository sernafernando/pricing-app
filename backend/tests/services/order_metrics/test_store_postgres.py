"""RED/GREEN -- `recompute_order_metrics` upserts `ml_order_metrics` (and
`ml_venta_deducciones`) instead of racing a read-then-`db.add` against a
concurrent caller (ventas-ml-rediseno PR1 review fix, post-merge).

Real Postgres, two independent sessions: `persistir_total_gauss`'s callers
(the background sweep, per-order writes on ingestion) can legitimately
recompute the SAME order concurrently with no existing `ml_order_metrics`
row yet. The old code read `existing_metrics` first and only then decided
insert vs. update -- two sessions racing that read both decide "insert",
and the SECOND session's flush/commit hits the primary key and raises
`IntegrityError`, aborting that caller's whole batch. An upsert
(`INSERT ... ON CONFLICT DO UPDATE`) makes the second writer update instead
of crash.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.ml_orders_ops import MlOrdersOps
from app.services.order_metrics.store import recompute_order_metrics


def _order(session, order_id: int) -> None:
    session.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 8, 15, tzinfo=timezone.utc),
            seller_id=999,
        )
    )
    session.commit()


@pytest.mark.postgres
class TestRecomputeOrderMetricsConcurrentUpsert:
    def test_two_concurrent_recomputes_of_a_new_order_never_raise_integrity_error(
        self, pg_order_metrics_engine
    ) -> None:
        order_id = 990001
        setup_conn = pg_order_metrics_engine.connect()
        Session = sessionmaker(bind=setup_conn)
        setup_session = Session()
        _order(setup_session, order_id)
        setup_session.close()
        setup_conn.close()

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def _worker() -> None:
            connection = pg_order_metrics_engine.connect()
            session = sessionmaker(bind=connection)()
            try:
                barrier.wait(timeout=5)
                recompute_order_metrics(session, [order_id])
                session.commit()
            except BaseException as exc:  # noqa: BLE001 -- captured across threads, re-raised in the main thread
                session.rollback()
                errors.append(exc)
            finally:
                session.close()
                connection.close()

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # A thread still alive means it is blocked (a lock it never gets, or
        # a deadlock the key ordering is supposed to prevent). Without this
        # check an empty `errors` would read as success while one worker
        # never finished.
        alive = [t.name for t in threads if t.is_alive()]
        assert not alive, f"worker(s) still blocked after 15s: {alive}"
        assert not errors, f"concurrent recompute raised: {errors!r}"

        verify_conn = pg_order_metrics_engine.connect()
        verify_session = sessionmaker(bind=verify_conn)()
        from app.models.ml_order_metrics import MlOrderMetrics

        rows = verify_session.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).all()
        assert len(rows) == 1
        verify_session.close()
        verify_conn.close()

    def test_second_recompute_of_the_same_order_updates_not_duplicates(self, pg_order_metrics_db) -> None:
        order_id = 990002
        _order(pg_order_metrics_db, order_id)

        recompute_order_metrics(pg_order_metrics_db, [order_id])
        pg_order_metrics_db.commit()

        recompute_order_metrics(pg_order_metrics_db, [order_id])
        pg_order_metrics_db.commit()

        from app.models.ml_order_metrics import MlOrderMetrics

        rows = pg_order_metrics_db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).all()
        assert len(rows) == 1

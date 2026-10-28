"""`ml_orders.quarantine_retry`: the worker retries quarantined ML orders on
its own (woken by `ml_orders_quarantine`, and on every safety poll), so a sale
that failed to ingest lands without anyone reading an alarm.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from typing import Iterator

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlOrdersOpsCuarentena
from app.services.ml_orders_ingestion import activity_receiver_service, ingestion_service
from app.workers.context import WorkerContext
from app.workers.handlers import ml_orders_quarantine as handler_module
from app.workers.handlers.ml_orders_quarantine import quarantine_retry
from app.workers.registry import REGISTRY
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

_TABLES = [MlOrdersOps.__table__, MlOrderItemOps.__table__, MlOrdersOpsCuarentena.__table__]


@pytest.fixture(scope="module")
def pg_quarantine_engine() -> Iterator[Engine]:
    """Own engine, creating only the tables that are missing and dropping
    only those: other module-scoped fixtures create and drop `ml_orders_ops`
    in the same physical database, so borrowing theirs depends on run order."""
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_TABLES)
    engine = create_engine(POSTGRES_TEST_URL)
    existing = set(inspect(engine).get_table_names())
    created = [t for t in _TABLES if t.name not in existing]
    for table in created:
        table.create(bind=engine)
    yield engine
    for table in reversed(created):
        table.drop(bind=engine)
    engine.dispose()


def _payload(order_id: int) -> dict:
    return {
        "id": order_id,
        "status": "paid",
        "date_created": "2026-10-18T10:00:00.000-03:00",
        "date_last_updated": "2026-10-18T10:00:00.000-03:00",
        "seller": {"id": 999},
        "buyer": {"id": 55, "nickname": "comprador"},
        "total_amount": 100.0,
        "paid_amount": 100.0,
        "currency_id": "ARS",
        "order_items": [{"item": {"id": "MLA1", "seller_sku": "SKU-1"}, "quantity": 1, "unit_price": 100.0}],
    }


class TestRegistration:
    def test_registered_and_woken_by_the_quarantine_channel(self) -> None:
        names = {h.name: h for h in REGISTRY}
        handler = names["ml_orders.quarantine_retry"]
        assert handler is quarantine_retry
        assert handler.channels == (ingestion_service.QUARANTINE_CHANNEL,)
        assert ingestion_service.QUARANTINE_CHANNEL == "ml_orders_quarantine"

    def test_runs_on_every_wake_and_safety_poll(self) -> None:
        """No `interval`/`run_at_local`: `WorkerRuntime.drain_once` only runs
        a handler on a LISTEN wake when it has neither (a scheduled handler
        would ignore the notify). The backoff, not the schedule, decides what
        is retried."""
        assert quarantine_retry.interval is None
        assert quarantine_retry.run_at_local is None


@pytest.mark.postgres
class TestRetriesQuarantinedOrders:
    @pytest.fixture()
    def _session(self, monkeypatch, pg_quarantine_engine):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        monkeypatch.setattr(ingestion_service, "congelar", lambda db, order_id, items: None)
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=pg_quarantine_engine, autoflush=False))
        yield
        with Session(bind=pg_quarantine_engine) as session:
            session.query(MlOrdersOpsCuarentena).delete()
            session.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_([4001, 4002])).delete()
            session.commit()

    def _quarantine(self, engine, order_id: int, ago: timedelta) -> None:
        last = datetime.now(timezone.utc) - ago
        with Session(bind=engine) as session:
            session.add(
                MlOrdersOpsCuarentena(
                    order_id=order_id,
                    raw_order=_payload(order_id),
                    error="[transient] QueuePool limit reached",
                    intentos=3,
                    primera_falla_at=last,
                    ultimo_intento_at=last,
                )
            )
            session.commit()

    def test_a_due_order_lands_and_leaves_quarantine(self, _session, pg_quarantine_engine) -> None:
        self._quarantine(pg_quarantine_engine, 4001, ago=timedelta(hours=1))

        result = quarantine_retry.run(
            WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")
        )

        assert result.success is True
        assert result.detail["recovered"] == 1
        with Session(bind=pg_quarantine_engine) as session:
            assert session.query(MlOrdersOps).filter_by(order_id=4001).count() == 1
            assert session.query(MlOrdersOpsCuarentena).filter_by(order_id=4001).count() == 0

    def test_an_order_inside_its_backoff_is_left_alone(self, _session, pg_quarantine_engine) -> None:
        self._quarantine(pg_quarantine_engine, 4002, ago=timedelta(minutes=1))

        result = quarantine_retry.run(
            WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")
        )

        assert result.detail["attempted"] == 0
        with Session(bind=pg_quarantine_engine) as session:
            assert session.query(MlOrdersOpsCuarentena).filter_by(order_id=4002).count() == 1


class TestTheHandlerNeverSpins:
    def test_a_full_pass_of_rows_that_stay_due_ends_the_run(self, monkeypatch) -> None:
        """If a pass returns only orders this run already attempted, retrying
        again would replay them until the deadline: the run stops instead."""
        limit = ingestion_service.MAX_QUARANTINE_RETRIES_PER_PASS
        same_rows = list(range(1, limit + 1))
        calls = []

        def _retry(db, limit):
            calls.append(limit)
            return ingestion_service.QuarantineRetryResult(
                attempted=limit, still_failed=limit, order_ids=list(same_rows)
            )

        @contextmanager
        def _no_db():
            yield None

        monkeypatch.setattr(ingestion_service, "retry_quarantined_orders", _retry)
        monkeypatch.setattr(handler_module, "get_background_db", _no_db)

        result = quarantine_retry.run(
            WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")
        )

        assert result.success is True
        assert len(calls) == 2
        # Both passes replayed the rows, so both count.
        assert result.detail["attempted"] == 2 * limit
        assert result.detail["passes"] == 2


class TestTheRefetchRunsBeforeTheReplay:
    def test_orders_ml_gave_back_are_replayed_in_the_same_run(self, monkeypatch) -> None:
        """remove-ml-divergences D2c: a run first asks ML again for the payload-less rows (bounded by the run's
        deadline), then replays, so an order ML gave back lands in that same run."""
        calls = []

        def _refetch(deadline):
            calls.append(("refetch", deadline))
            return activity_receiver_service.RefetchResult(attempted=3, landed=1, dropped=1, failed=1)

        def _retry(db, limit):
            calls.append(("replay", limit))
            return ingestion_service.QuarantineRetryResult(attempted=1, recovered=1, order_ids=[1])

        @contextmanager
        def _no_db():
            yield None

        monkeypatch.setattr(activity_receiver_service, "refetch_unresolved_orders", _refetch)
        monkeypatch.setattr(ingestion_service, "retry_quarantined_orders", _retry)
        monkeypatch.setattr(handler_module, "get_background_db", _no_db)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=30)

        result = quarantine_retry.run(WorkerContext(deadline=deadline, worker_name="w"))

        assert [c[0] for c in calls] == ["refetch", "replay"]
        # At most half of the run's time, so a slow proxy cannot leave the replay none.
        assert datetime.now(timezone.utc) < calls[0][1] <= deadline - timedelta(seconds=14)
        assert result.detail["refetched"] == 3
        assert result.detail["refetch_landed"] == 1
        assert result.detail["dropped"] == 1
        assert result.detail["refetch_failed"] == 1
        assert result.detail["recovered"] == 1

    def test_a_refetch_that_raises_does_not_stop_the_replay(self, monkeypatch, caplog) -> None:
        """The re-fetch is a separate concern: if it fails (the pool, the proxy), the orders whose write failed are
        still replayed."""

        def _refetch(deadline):
            raise RuntimeError("pool timeout")

        def _retry(db, limit):
            return ingestion_service.QuarantineRetryResult(attempted=1, recovered=1, order_ids=[1])

        @contextmanager
        def _no_db():
            yield None

        monkeypatch.setattr(activity_receiver_service, "refetch_unresolved_orders", _refetch)
        monkeypatch.setattr(ingestion_service, "retry_quarantined_orders", _retry)
        monkeypatch.setattr(handler_module, "get_background_db", _no_db)

        with caplog.at_level("ERROR"):
            result = quarantine_retry.run(
                WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")
            )

        assert result.success is True
        assert result.detail["recovered"] == 1
        assert result.detail["refetched"] == 0
        assert any("re-fetch" in r.getMessage() for r in caplog.records)

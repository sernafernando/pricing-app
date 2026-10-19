"""`ml_orders.quarantine_retry`: the worker retries quarantined ML orders on
its own (woken by `ml_orders_quarantine`, and on every safety poll), so a sale
that failed to ingest lands without anyone reading an alarm.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from typing import Iterator

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlOrdersOpsCuarentena
from app.services.ml_orders_ingestion import ingestion_service
from app.workers.context import WorkerContext
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

"""`sell.drain` (sell-in-sell-out T4): INERT until T5. It claims queued sale
lines and acks them without computing any allocation.

Postgres only: the queue is claimed with `FOR UPDATE SKIP LOCKED`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Tuple

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_dirty import SellDirty
from app.models.sell_in import SellInConsumo
from app.services.sell import queue
from app.workers.context import WorkerContext
from app.workers.handlers.sell_drain import drain as handler
from app.workers.registry import REGISTRY
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types


@pytest.fixture(scope="module")
def pg_sell_drain_engine() -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    table = SellDirty.__table__
    _restore_pristine_pg_types([table])
    engine = create_engine(POSTGRES_TEST_URL)
    created = not inspect(engine).has_table(table.name)
    if created:
        table.create(bind=engine)
    yield engine
    if created:
        table.drop(bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, pg_sell_drain_engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=pg_sell_drain_engine))
    yield
    with pg_sell_drain_engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))


def _queue(engine: Engine, *lines: Tuple[str, int, int]) -> None:
    with engine.begin() as conn:
        for canal, ref, item in lines:
            conn.execute(
                text("INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES (:c, :r, :i)"),
                {"c": canal, "r": ref, "i": item},
            )


def _queued(engine: Engine) -> List[int]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT venta_ref FROM sell_dirty ORDER BY venta_ref"))]


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")


@pytest.mark.postgres
class TestInertDrain:
    def test_it_is_registered_and_woken_by_its_channel(self) -> None:
        assert handler in REGISTRY
        assert handler.name == "sell.drain"
        assert handler.channels == (queue.CHANNEL,) == ("sell_dirty",)
        assert handler.interval is None and handler.run_at_local is None

    def test_it_acks_every_queued_line_in_batches(self, pg_sell_drain_engine: Engine) -> None:
        canales = ("ml", "fuera", "tn")
        _queue(pg_sell_drain_engine, *((canales[n % 3], 590_000 + n, 2964) for n in range(queue.BATCH_SIZE + 3)))

        result = handler.run(_ctx())

        assert result.success
        assert result.detail == {"acked": queue.BATCH_SIZE + 3, "batches": 2}
        assert _queued(pg_sell_drain_engine) == []

    def test_it_computes_nothing(self) -> None:
        """Inert: the handler module never touches an allocation table."""
        import inspect as pyinspect

        from app.workers.handlers import sell_drain

        source = pyinspect.getsource(sell_drain)
        assert SellInConsumo.__tablename__ not in source
        assert "sell_out" not in source

    def test_an_empty_queue_is_one_cheap_pass(self) -> None:
        result = handler.run(_ctx())

        assert result.success and result.detail == {"acked": 0, "batches": 0}

    def test_a_line_locked_by_another_drain_is_skipped_not_waited_for(self, pg_sell_drain_engine: Engine) -> None:
        _queue(pg_sell_drain_engine, ("fuera", 1, 950), ("fuera", 2, 950))
        with pg_sell_drain_engine.connect() as other:
            other.execute(text("SELECT 1 FROM sell_dirty WHERE venta_ref = 1 FOR UPDATE"))

            with sessionmaker(bind=pg_sell_drain_engine)() as s:
                acked = queue.ack_batch(s, queue.BATCH_SIZE)
                s.commit()

            other.rollback()

        assert acked == [("fuera", 2, 950)]
        assert _queued(pg_sell_drain_engine) == [1]

"""`sell_dirty` triggers (sell-in-sell-out T4): a fuera or Tienda Nube sale
that appears, changes what the allocation reads, or disappears queues its line.

Postgres only: the queue is fed by row triggers on the fuera and Tienda Nube
sale tables and woken with `pg_notify`.
The fixture rows are shaped like production rows (it_transaction, item_id,
cantidad 1.0000, fecha_venta at midnight UTC, sd_id 1, signo 1).
"""

from __future__ import annotations

import itertools
import select
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterator, List, Tuple, Type

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.sell_dirty import SellDirty
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.sell import queue
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

_TABLES = [VentaFueraMLMetrica.__table__, VentaTiendaNubeMetrica.__table__, SellDirty.__table__]
_CANALES: List[Tuple[str, Type]] = [("fuera", VentaFueraMLMetrica), ("tn", VentaTiendaNubeMetrica)]
_ids = itertools.count(590_000)


@pytest.fixture(scope="module")
def pg_sell_engine() -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_TABLES)
    engine = create_engine(POSTGRES_TEST_URL)
    existing = set(inspect(engine).get_table_names())
    created = [t for t in _TABLES if t.name not in existing]
    for table in created:
        table.create(bind=engine)
    with engine.begin() as conn:
        installed = conn.execute(text("SELECT 1 FROM pg_proc WHERE proname = 'sell_dirty_enqueue_venta'")).first()
        if installed is None:
            for statement in queue.UPGRADE_SQL:
                conn.execute(text(statement))
    yield engine
    if installed is None:
        with engine.begin() as conn:
            for statement in queue.DOWNGRADE_SQL:
                conn.execute(text(statement))
    for table in reversed(created):
        table.drop(bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, pg_sell_engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=pg_sell_engine))
    yield
    with pg_sell_engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(f"DELETE FROM {table.name}"))


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine)()


def _queued(engine: Engine) -> List[Tuple[str, int, int]]:
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(text("SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY canal, venta_ref"))
        ]


def _clear_queue(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))


def _venta(engine: Engine, model: Type, item_id: int = 2964, cantidad: str = "1.0000") -> int:
    it_transaction = next(_ids)
    with _session(engine) as s:
        s.add(
            model(
                it_transaction=it_transaction,
                ct_transaction=it_transaction + 1,
                item_id=item_id,
                codigo="X",
                fecha_venta=datetime(2026, 10, 16, tzinfo=timezone.utc),
                sd_id=1,
                signo=1,
                cantidad=Decimal(cantidad),
                monto_total=Decimal("54298.64"),
                costo_unitario=Decimal("41081.895750"),
                cliente="Cliente",
            )
        )
        s.commit()
    return it_transaction


def _update(engine: Engine, model: Type, it_transaction: int, **values) -> None:
    sets = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {model.__tablename__} SET {sets} WHERE it_transaction = :it"),
            {"it": it_transaction, **values},
        )


@pytest.mark.postgres
@pytest.mark.parametrize("canal,model", _CANALES)
class TestTriggers:
    def test_a_new_sale_queues_its_line_and_product(self, pg_sell_engine: Engine, canal: str, model: Type) -> None:
        ref = _venta(pg_sell_engine, model, item_id=2964)

        assert _queued(pg_sell_engine) == [(canal, ref, 2964)]

    def test_a_change_to_what_the_allocation_reads_queues_the_line(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        refs = [_venta(pg_sell_engine, model) for _ in range(5)]
        _clear_queue(pg_sell_engine)

        _update(pg_sell_engine, model, refs[0], cantidad=Decimal("2"))
        _update(pg_sell_engine, model, refs[1], fecha_venta=datetime(2026, 10, 1, tzinfo=timezone.utc))
        _update(pg_sell_engine, model, refs[2], monto_total=Decimal("1"))
        _update(pg_sell_engine, model, refs[3], costo_unitario=Decimal("1"))
        _update(pg_sell_engine, model, refs[4], signo=-1)

        assert [row[1] for row in _queued(pg_sell_engine)] == refs

    def test_a_product_change_queues_the_line_under_its_new_product(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model, item_id=2964)
        _clear_queue(pg_sell_engine)

        _update(pg_sell_engine, model, ref, item_id=950)

        assert _queued(pg_sell_engine) == [(canal, ref, 950)]

    def test_an_update_that_changes_nothing_relevant_queues_nothing(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model)
        _clear_queue(pg_sell_engine)

        # The ERP sync rewrites rows with the same values, and touches columns
        # the allocation never reads.
        _update(pg_sell_engine, model, ref, cantidad=Decimal("1.0000"), cliente="Otro", vendedor="V")

        assert _queued(pg_sell_engine) == []

    def test_a_deleted_sale_queues_its_line_to_release_it(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model, item_id=2267)
        _clear_queue(pg_sell_engine)

        with pg_sell_engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {model.__tablename__} WHERE it_transaction = :it"), {"it": ref})

        assert _queued(pg_sell_engine) == [(canal, ref, 2267)]

    def test_a_queued_line_is_queued_once_and_a_requeue_resets_its_attempts(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model)
        with pg_sell_engine.begin() as conn:
            conn.execute(text("UPDATE sell_dirty SET attempts = 3, last_error = 'boom'"))

        _update(pg_sell_engine, model, ref, cantidad=Decimal("4"))

        with pg_sell_engine.connect() as conn:
            rows = conn.execute(text("SELECT attempts, last_error FROM sell_dirty")).all()
        assert [tuple(r) for r in rows] == [(0, None)]

    def test_the_trigger_notifies_the_channel(self, pg_sell_engine: Engine, canal: str, model: Type) -> None:
        raw = pg_sell_engine.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            cursor = raw.cursor()
            cursor.execute(f"LISTEN {queue.CHANNEL}")
            _venta(pg_sell_engine, model)
            select.select([raw.driver_connection], [], [], 5)
            raw.driver_connection.poll()
            channels = [n.channel for n in raw.driver_connection.notifies]
        finally:
            # Never hand an autocommit connection back to the pool.
            raw.invalidate()

        assert queue.CHANNEL in channels

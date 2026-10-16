"""`tp_cost.fill` (metricas-ml-tplink-mode P2): when a list-8 price shows up,
the sales still flagged without a TP cost are filled once, by the worker, with
the same resolver and rules as `app/scripts/backfill_tp_cost.py`.

Postgres only: the queue is fed by triggers on the ERP cost tables, claimed
with `FOR UPDATE SKIP LOCKED`, and woken by `pg_notify`.
"""

from __future__ import annotations

import itertools
import select
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterator, List, Optional, Sequence

import pytest
from sqlalchemy import Engine, Row, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.item_cost_list import ItemCostList
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrdersOps
from app.models.tb_item_association import TbItemAssociation
from app.models.tipo_cambio import TipoCambio
from app.services.ml_orders_ingestion import tp_cost_resolver as resolver
from app.services.ml_orders_ingestion import tp_cost_fill
from app.workers.context import WorkerContext
from app.workers.handlers.tp_cost_fill import fill as handler
from app.workers.registry import REGISTRY
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

_TABLES = [
    MlOrdersOps.__table__,
    MlOrderItemCosto.__table__,
    ItemCostList.__table__,
    ItemCostListHistory.__table__,
    TbItemAssociation.__table__,
    TipoCambio.__table__,
]
_ids = itertools.count(1)


def _install_queue(engine: Engine) -> bool:
    """Installs the queue and its triggers unless the migration (or an earlier
    run) already did: returns whether THIS call installed them, so teardown
    only drops what the fixture created."""
    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass('tp_cost_fill_queue')")).scalar() is not None:
            return False
        for statement in tp_cost_fill.UPGRADE_SQL:
            conn.execute(text(statement))
    return True


def _triggers(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'trg_tp_cost_fill%'")).scalar()


def _queue_row(engine: Engine, item_id: int) -> Optional[Row]:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT attempts, last_error FROM tp_cost_fill_queue WHERE item_id = :i"), {"i": item_id}
        ).one_or_none()


@pytest.fixture(scope="module")
def pg_tp_engine() -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(POSTGRES_TEST_URL)
    existing = set(inspect(engine).get_table_names())
    created = [t for t in _TABLES if t.name not in existing]
    for table in created:
        table.create(bind=engine)
    installed = _install_queue(engine)
    yield engine
    if installed:
        with engine.begin() as conn:
            for statement in tp_cost_fill.DOWNGRADE_SQL:
                conn.execute(text(statement))
    for table in reversed(created):
        table.drop(bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, pg_tp_engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=pg_tp_engine))
    yield
    with pg_tp_engine.begin() as conn:
        for table in [*_TABLES, "tp_cost_fill_queue"]:
            name = table if isinstance(table, str) else table.name
            conn.execute(text(f"DELETE FROM {name}"))


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine)()


def _queued(engine: Engine) -> List[int]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT item_id FROM tp_cost_fill_queue ORDER BY item_id"))]


def _clear_queue(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tp_cost_fill_queue"))


def _venta(session: Session, order_id: int, producto_item_id: int, when: date = date(2026, 10, 1), **tp: Any) -> None:
    moment = datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc)
    session.add(MlOrdersOps(order_id=order_id, seller_id=1, date_created=moment, ml_last_updated=moment))
    session.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=f"MLA{order_id}",
            costo_origen=Decimal("100"),
            moneda="ARS",
            costo_unitario_ars=Decimal("100"),
            iva_pct=Decimal("21"),
            precio_unitario=Decimal("1000"),
            fuente="erp_publicacion",
            producto_item_id=producto_item_id,
            **tp,
        )
    )


def _hist(session: Session, item_id: int, price: float, when: date, coslis_id: int = 8, curr_id: int = 1) -> None:
    session.add(
        ItemCostListHistory(
            iclh_id=next(_ids),
            comp_id=1,
            coslis_id=coslis_id,
            item_id=item_id,
            iclh_price=price,
            curr_id=curr_id,
            iclh_cd=datetime.combine(when, datetime.min.time()),
        )
    )


def _lista(session: Session, item_id: int, price: float, coslis_id: int = 8, curr_id: int = 1) -> None:
    session.add(ItemCostList(comp_id=1, coslis_id=coslis_id, item_id=item_id, coslis_price=price, curr_id=curr_id))


def _tp(engine: Engine, order_id: int) -> Row:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT costo_tp_unitario_ars, costo_tp_fuente FROM ml_order_item_costos WHERE order_id = :o"),
            {"o": order_id},
        ).one()


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")


@pytest.mark.postgres
class TestTrigger:
    def test_a_list8_insert_enqueues_the_item_and_other_lists_do_not(self, pg_tp_engine: Engine) -> None:
        with _session(pg_tp_engine) as s:
            _lista(s, 500, 80)
            _lista(s, 501, 80, coslis_id=1)
            s.commit()

        assert _queued(pg_tp_engine) == [500]

    def test_a_price_or_currency_change_enqueues_and_a_no_op_update_does_not(self, pg_tp_engine: Engine) -> None:
        with _session(pg_tp_engine) as s:
            _lista(s, 500, 80)
            _lista(s, 501, 80)
            _lista(s, 502, 80)
            _lista(s, 503, 80, coslis_id=1)
            s.commit()
        _clear_queue(pg_tp_engine)

        with pg_tp_engine.begin() as conn:
            conn.execute(text("UPDATE tb_item_cost_list SET coslis_price = 90 WHERE item_id = 500"))
            conn.execute(text("UPDATE tb_item_cost_list SET curr_id = 2 WHERE item_id = 501"))
            conn.execute(text("UPDATE tb_item_cost_list SET coslis_price = 80, coslis_cd = now() WHERE item_id = 502"))
            conn.execute(text("UPDATE tb_item_cost_list SET coslis_price = 99 WHERE item_id = 503"))

        assert _queued(pg_tp_engine) == [500, 501]

    def test_a_list8_history_row_enqueues_its_item(self, pg_tp_engine: Engine) -> None:
        """The resolver reads the HISTORY, and the ERP sync writes the current
        list before the history: the history insert must wake the fill too."""
        with _session(pg_tp_engine) as s:
            _hist(s, 600, 80, date(2026, 10, 1))
            _hist(s, 601, 80, date(2026, 10, 1), coslis_id=1)
            s.commit()

        assert _queued(pg_tp_engine) == [600]

    def test_the_trigger_notifies_the_channel(self, pg_tp_engine: Engine) -> None:
        raw = pg_tp_engine.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            cursor = raw.cursor()
            cursor.execute(f"LISTEN {tp_cost_fill.CHANNEL}")
            with _session(pg_tp_engine) as s:
                _lista(s, 500, 80)
                s.commit()
            select.select([raw.driver_connection], [], [], 5)
            raw.driver_connection.poll()
            channels = [n.channel for n in raw.driver_connection.notifies]
        finally:
            # Never hand an autocommit connection back to the pool: the next
            # session would run without a transaction (and without savepoints).
            raw.invalidate()

        assert tp_cost_fill.CHANNEL in channels


@pytest.mark.postgres
class TestHandler:
    def test_it_is_registered_and_woken_by_its_channel(self) -> None:
        assert handler in REGISTRY
        assert handler.channels == (tp_cost_fill.CHANNEL,)
        assert handler.interval is None and handler.run_at_local is None

    def test_it_fills_null_rows_of_the_item_and_leaves_set_ones_alone(self, pg_tp_engine: Engine) -> None:
        with _session(pg_tp_engine) as s:
            _venta(s, 1, 500)
            _venta(
                s,
                2,
                500,
                costo_tp_origen=Decimal("11"),
                costo_tp_moneda="ARS",
                costo_tp_unitario_ars=Decimal("11"),
                costo_tp_fuente="lista8_ingesta",
                costo_tp_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            )
            _venta(s, 3, 777)  # another item, not queued: untouched
            _hist(s, 500, 80, date(2026, 9, 1))
            _hist(s, 777, 80, date(2026, 9, 1))
            s.commit()
        with pg_tp_engine.begin() as conn:
            conn.execute(text("DELETE FROM tp_cost_fill_queue WHERE item_id = 777"))

        result = handler.run(_ctx())

        assert result.success
        assert _tp(pg_tp_engine, 1) == (Decimal("80.0000"), resolver.FUENTE_TP_HISTORIA)
        assert _tp(pg_tp_engine, 2) == (Decimal("11.0000"), "lista8_ingesta")
        assert _tp(pg_tp_engine, 3) == (None, None)
        assert _queued(pg_tp_engine) == []
        assert result.detail["items"] == 1
        assert result.detail["written"] == 1

    def test_a_later_first_price_fills_with_the_approximate_fuente(self, pg_tp_engine: Engine) -> None:
        with _session(pg_tp_engine) as s:
            _venta(s, 4, 500, when=date(2026, 9, 1))
            _hist(s, 500, 80, date(2026, 10, 15))
            s.commit()

        handler.run(_ctx())

        assert _tp(pg_tp_engine, 4) == (Decimal("80.0000"), resolver.FUENTE_TP_PRIMER_PRECIO)

    def test_a_combo_containing_the_queued_component_is_filled(self, pg_tp_engine: Engine) -> None:
        with _session(pg_tp_engine) as s:
            _venta(s, 5, 900)
            s.add(TbItemAssociation(comp_id=1, itema_id=next(_ids), item_id=900, item_id_1=901, iasso_qty=2))
            s.add(TbItemAssociation(comp_id=1, itema_id=next(_ids), item_id=900, item_id_1=902, iasso_qty=1))
            _hist(s, 902, 5, date(2026, 9, 1))
            s.commit()
        _clear_queue(pg_tp_engine)
        with _session(pg_tp_engine) as s:
            _hist(s, 901, 30, date(2026, 9, 1))  # the missing component arrives
            s.commit()

        handler.run(_ctx())

        assert _tp(pg_tp_engine, 5) == (Decimal("65.0000"), resolver.FUENTE_TP_HISTORIA_COMBO)

    def test_an_item_still_without_a_price_is_dequeued_and_stays_null(self, pg_tp_engine: Engine) -> None:
        with _session(pg_tp_engine) as s:
            _venta(s, 6, 500)
            _hist(s, 500, 0, date(2026, 9, 1))
            s.commit()

        handler.run(_ctx())

        assert _tp(pg_tp_engine, 6) == (None, None)
        assert _queued(pg_tp_engine) == []

    def test_it_drains_the_queue_in_batches(self, pg_tp_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tp_cost_fill, "BATCH_ITEMS", 1)
        with _session(pg_tp_engine) as s:
            for order_id, item in ((7, 500), (8, 501), (9, 502)):
                _venta(s, order_id, item)
                _hist(s, item, 80, date(2026, 9, 1))
            s.commit()

        result = handler.run(_ctx())

        assert result.detail["batches"] == 3
        assert result.detail["items"] == 3
        assert [_tp(pg_tp_engine, o)[0] for o in (7, 8, 9)] == [Decimal("80.0000")] * 3

    def test_an_empty_queue_costs_one_query(self, pg_tp_engine: Engine) -> None:
        statements: List[str] = []

        def _record(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
            statements.append(statement)

        event.listen(pg_tp_engine, "before_cursor_execute", _record)
        try:
            result = handler.run(_ctx())
        finally:
            event.remove(pg_tp_engine, "before_cursor_execute", _record)

        assert result.success
        assert result.detail == {"items": 0, "batches": 0, "written": 0, "failed": 0, "combo_failed": 0}
        queries = [s for s in statements if "tp_cost_fill_queue" in s]
        assert len(queries) == 1
        assert not [s for s in statements if "ml_order_item_costos" in s]


def test_the_migration_carries_the_live_definition() -> None:
    """The migration is a frozen copy of `tp_cost_fill.UPGRADE_SQL`/`DOWNGRADE_SQL`."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20261029_tp_cost_fill_queue.py"
    spec = importlib.util.spec_from_file_location("tp_cost_fill_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._UPGRADE == tp_cost_fill.UPGRADE_SQL
    assert module._DOWNGRADE == tp_cost_fill.DOWNGRADE_SQL
    assert module.down_revision == "20261028_tplink_solo_permiso"


@pytest.mark.postgres
class TestFixture:
    def test_installing_again_over_an_installed_schema_is_a_no_op(self, pg_tp_engine: Engine) -> None:
        assert _install_queue(pg_tp_engine) is False
        assert _triggers(pg_tp_engine) == 3


def _poison(monkeypatch: pytest.MonkeyPatch, bad_item: int, *, after_writing: bool = False) -> None:
    """Makes the fill raise for `bad_item`'s rows -- after writing them when
    `after_writing`, to prove the write is rolled back."""
    original = tp_cost_fill.procesar_lote

    def _maybe_raise(db: Session, rows: Sequence[Any], dry_run: bool, result: resolver.BackfillTpResult) -> None:
        if any(row.producto_item_id == bad_item for row in rows):
            if after_writing:
                original(db, rows, dry_run, result)
            raise RuntimeError(f"boom {bad_item}")
        return original(db, rows, dry_run, result)

    monkeypatch.setattr(tp_cost_fill, "procesar_lote", _maybe_raise)


@pytest.mark.postgres
class TestPoisonedItems:
    def _seed(self, engine: Engine, items: Sequence[int]) -> None:
        with _session(engine) as s:
            for order_id, item in enumerate(items, start=100):
                _venta(s, order_id, item)
                _hist(s, item, 80, date(2026, 9, 1))
            s.commit()

    def test_a_failing_item_is_charged_and_the_others_in_its_batch_are_filled(
        self, pg_tp_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._seed(pg_tp_engine, [500, 501, 502])
        _poison(monkeypatch, 501)

        result = handler.run(_ctx())

        assert result.success
        assert _tp(pg_tp_engine, 100)[0] == Decimal("80.0000")
        assert _tp(pg_tp_engine, 102)[0] == Decimal("80.0000")
        assert _tp(pg_tp_engine, 101) == (None, None)
        attempts, last_error = _queue_row(pg_tp_engine, 501)
        assert attempts == 1 and "boom 501" in last_error
        assert _queued(pg_tp_engine) == [501]
        assert result.detail["failed"] == 1

    def test_a_failure_after_writing_rolls_the_item_back(
        self, pg_tp_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._seed(pg_tp_engine, [500])
        _poison(monkeypatch, 500, after_writing=True)

        handler.run(_ctx())

        assert _tp(pg_tp_engine, 100) == (None, None)
        assert _queue_row(pg_tp_engine, 500)[0] == 1

    def test_an_item_failing_on_every_run_is_parked_and_never_starves_new_ones(
        self, pg_tp_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._seed(pg_tp_engine, [500])
        _poison(monkeypatch, 500)
        monkeypatch.setattr(tp_cost_fill, "BATCH_ITEMS", 1)

        for run in range(tp_cost_fill.MAX_ATTEMPTS + 2):
            with _session(pg_tp_engine) as s:  # a new item arrives every run
                _venta(s, 200 + run, 600 + run)
                _hist(s, 600 + run, 80, date(2026, 9, 1))
                s.commit()
            handler.run(_ctx())
            assert _tp(pg_tp_engine, 200 + run)[0] == Decimal("80.0000")

        assert _queue_row(pg_tp_engine, 500)[0] == tp_cost_fill.MAX_ATTEMPTS
        assert _queued(pg_tp_engine) == [500]

    def test_a_parked_item_is_not_claimed_and_costs_one_query(
        self, pg_tp_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._seed(pg_tp_engine, [500])
        with pg_tp_engine.begin() as conn:
            conn.execute(text("UPDATE tp_cost_fill_queue SET attempts = :n"), {"n": tp_cost_fill.MAX_ATTEMPTS})
        statements: List[str] = []

        def _record(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
            statements.append(statement)

        event.listen(pg_tp_engine, "before_cursor_execute", _record)
        try:
            result = handler.run(_ctx())
        finally:
            event.remove(pg_tp_engine, "before_cursor_execute", _record)

        assert result.detail["items"] == 0
        assert len([s for s in statements if "tp_cost_fill_queue" in s]) == 1
        assert _tp(pg_tp_engine, 100) == (None, None)

    def test_a_new_list8_change_unparks_the_item(self, pg_tp_engine: Engine) -> None:
        self._seed(pg_tp_engine, [500])
        with pg_tp_engine.begin() as conn:
            conn.execute(
                text("UPDATE tp_cost_fill_queue SET attempts = :n, last_error = 'x'"),
                {"n": tp_cost_fill.MAX_ATTEMPTS},
            )
        with _session(pg_tp_engine) as s:
            _hist(s, 500, 90, date(2026, 9, 2))
            s.commit()

        assert _queue_row(pg_tp_engine, 500) == (0, None)

    def test_an_error_outside_any_item_rolls_the_whole_batch_back(
        self, pg_tp_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._seed(pg_tp_engine, [500])

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("combo lookup failed")

        monkeypatch.setattr(tp_cost_fill, "_combos_de", _boom)

        with pytest.raises(RuntimeError):
            handler.run(_ctx())

        assert _queue_row(pg_tp_engine, 500) == (0, None)
        assert _tp(pg_tp_engine, 100) == (None, None)


@pytest.mark.postgres
class TestBrokenCombo:
    def test_a_broken_combo_never_charges_or_undoes_its_component(
        self, pg_tp_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _session(pg_tp_engine) as s:
            _venta(s, 300, 901)  # the component's own sale
            _venta(s, 301, 900)  # a sale of the combo that contains it
            s.add(TbItemAssociation(comp_id=1, itema_id=next(_ids), item_id=900, item_id_1=901, iasso_qty=1))
            _hist(s, 901, 30, date(2026, 9, 1))
            s.commit()
        _poison(monkeypatch, 900, after_writing=True)

        result = handler.run(_ctx())

        assert _tp(pg_tp_engine, 300) == (Decimal("30.0000"), resolver.FUENTE_TP_HISTORIA)
        assert _tp(pg_tp_engine, 301) == (None, None)
        assert _queue_row(pg_tp_engine, 901) is None
        assert result.detail["failed"] == 0
        assert result.detail["combo_failed"] == 1


@pytest.mark.postgres
class TestRowsResolvedOnce:
    def test_an_item_that_is_also_a_combo_of_another_queued_item_is_examined_once(self, pg_tp_engine: Engine) -> None:
        with _session(pg_tp_engine) as s:
            _venta(s, 400, 900)  # a sale of the combo
            _venta(s, 401, 901)  # a sale of its component
            s.add(TbItemAssociation(comp_id=1, itema_id=next(_ids), item_id=900, item_id_1=901, iasso_qty=1))
            _hist(s, 900, 50, date(2026, 9, 1))  # queues the combo itself
            _hist(s, 901, 30, date(2026, 9, 1))  # queues the component
            s.commit()
        assert _queued(pg_tp_engine) == [900, 901]

        with _session(pg_tp_engine) as s:
            batch = tp_cost_fill.fill_batch(s, limit=10)
            s.commit()

        assert batch.items == 2
        assert batch.result.examined == 2
        assert _tp(pg_tp_engine, 400)[0] == Decimal("50.0000")
        assert _tp(pg_tp_engine, 401)[0] == Decimal("30.0000")


def test_the_worker_never_imports_a_script_module() -> None:
    """Importing a script runs its `load_dotenv`: the worker must reach the
    resolver through the service module only."""
    import subprocess
    import sys

    code = (
        "import sys, app.workers.handlers.tp_cost_fill; "
        "print(sorted(m for m in sys.modules if m.startswith('app.scripts')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert out.stdout.strip().splitlines()[-1] == "[]"

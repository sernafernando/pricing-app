"""ODD `metricas-ml-tablero` review: concurrent refreshes of ONE (MLA, day)
bucket must never lose an order.

THE RACE: two worker transactions store two different sales of the same MLA
on the same day. Each recomputes the bucket from source; each misses the
OTHER's sale (not committed yet, invisible in its snapshot); both upsert;
the last upsert wins and the bucket silently undercounts -- nothing is left
dirty to fix it later.

This test reproduces it with two real Postgres connections and a fixed
interleaving: T1 writes sale A and refreshes the bucket (uncommitted); T2,
in another thread, writes sale B and refreshes the same bucket; a third
connection confirms (`pg_locks`) that T2 is waiting on T1; T1 commits; T2
commits. With the bucket lock the bucket holds A + B; the variant without
it shows the lost update.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ml_daily_metrics.rollup import refresh_rollup

MLA = "MLA6600000001"
DAY = date(2026, 9, 20)
ACCREDITED = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
ORDER_A = 2000066000000001
ORDER_B = 2000066000000002


@pytest.fixture(scope="module")
def engine():
    from tests.conftest import (
        POSTGRES_TEST_URL,
        _patch_pg_types_for_sqlite,
        _postgres_reachable,
        _restore_pristine_pg_types,
    )

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    from app.models.ml_daily_metrics import MlProductDailyMetrics
    from app.models.ml_group_metrics import MlGroupMetrics
    from app.models.ml_order_item_costo import MlOrderItemCosto
    from app.models.ml_order_metrics import MlOrderMetrics
    from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps

    tables = [
        MlOrdersOps.__table__,
        MlOrderItemOps.__table__,
        MlOrderItemCosto.__table__,
        MlOrderMetrics.__table__,
        MlGroupMetrics.__table__,
        MlProductDailyMetrics.__table__,
    ]
    _restore_pristine_pg_types(tables)
    eng = create_engine(POSTGRES_TEST_URL)
    created = []
    try:
        for table in tables:
            if not sa_inspect(eng).has_table(table.name):
                table.create(eng)
                created.append(table)
        _patch_pg_types_for_sqlite()
        yield eng
    finally:
        with eng.begin() as conn:
            for stmt in (
                "DELETE FROM ml_product_daily_metrics WHERE mla = :mla",
                "DELETE FROM ml_group_metrics WHERE group_key IN (:ka, :kb)",
                "DELETE FROM ml_order_metrics WHERE order_id IN (:a, :b)",
                "DELETE FROM ml_order_item_costos WHERE order_id IN (:a, :b)",
                "DELETE FROM ml_order_items_ops WHERE order_id IN (:a, :b)",
                "DELETE FROM ml_orders_ops WHERE order_id IN (:a, :b)",
            ):
                conn.execute(
                    text(stmt),
                    {"mla": MLA, "a": ORDER_A, "b": ORDER_B, "ka": f"o:{ORDER_A}", "kb": f"o:{ORDER_B}"},
                )
        for table in reversed(created):
            table.drop(eng, checkfirst=True)
        eng.dispose()


def _write_sale(session, order_id: int, qty: int) -> None:
    """Everything `refresh_rollup` reads for one lone, accredited sale."""
    params = {"oid": order_id, "qty": qty, "mla": MLA, "when": ACCREDITED, "key": f"o:{order_id}"}
    for stmt in (
        "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, currency_id) "
        "VALUES (:oid, 999, 'paid', :when, :when, 'ARS')",
        "INSERT INTO ml_order_items_ops (order_id, item_id, quantity, unit_price) VALUES (:oid, :mla, :qty, 100)",
        "INSERT INTO ml_order_item_costos (order_id, item_id, costo_origen, moneda, costo_unitario_ars, iva_pct, "
        "precio_unitario, fuente, producto_item_id, congelado_at) "
        "VALUES (:oid, :mla, 50, 'ARS', 50, 21, 100, 't', 6600, now())",
        "INSERT INTO ml_order_metrics (order_id, costo_mercaderia, total_gauss, gauss_status, formula_version, "
        "computed_at) VALUES (:oid, 50 * :qty, 10 * :qty, 'ok', 2, now())",
        "INSERT INTO ml_group_metrics (group_key, gauss_status, member_order_ids, group_date, formula_version, "
        "computed_at) VALUES (:key, 'ok', ARRAY[CAST(:oid AS BIGINT)], :when, 2, now())",
    ):
        session.execute(text(stmt), params)


def _wait_until_blocked(engine, *, waiter_pid: int, holder_pid: int, advisory: bool, timeout: float = 10.0) -> None:
    """Polls from a THIRD connection until the backend `waiter_pid` (T2) is
    blocked by `holder_pid` (T1) -- on an advisory lock when `advisory`, on
    any lock otherwise -- and fails if that never happens within `timeout`.
    Scoped to those two pids: `pg_locks` is cluster-wide, so an unrelated
    waiting backend must not satisfy it. A fixed sleep would only make the
    interleaving likely; this makes it certain."""
    query = (
        "SELECT CAST(:holder AS int) = ANY(pg_blocking_pids(:waiter)) AND EXISTS ("
        "SELECT 1 FROM pg_locks WHERE pid = :waiter AND NOT granted"
        + (" AND locktype = 'advisory'" if advisory else "")
        + ")"
    )
    deadline = time.monotonic() + timeout
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            if observer.execute(text(query), {"waiter": waiter_pid, "holder": holder_pid}).scalar():
                return
            observer.rollback()
            time.sleep(0.02)
    pytest.fail(f"the second refresh never blocked on the first ({'advisory' if advisory else 'any'} lock)")


@pytest.mark.postgres
@pytest.mark.parametrize("locked", [True, False], ids=["with-bucket-lock", "without-bucket-lock"])
def test_two_concurrent_refreshes_of_one_bucket(engine, monkeypatch, locked: bool) -> None:
    """With the bucket lock, T2 waits on it BEFORE reading and then sees A:
    the bucket holds A + B. The `without-bucket-lock` variant keeps the RED
    evidence reproducible: T2 reads without A, waits only on T1's row at the
    upsert, then overwrites it -- sale A is lost."""
    from app.services.ml_daily_metrics import rollup

    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    if not locked:
        monkeypatch.setattr(rollup, "_lock_buckets", lambda db, buckets: None)
    make = sessionmaker(bind=engine)
    t1, t2 = make(), make()
    errors: list = []
    t2_pid = None
    worker = None
    try:
        t1_pid = t1.execute(text("SELECT pg_backend_pid()")).scalar()
        t2_pid = t2.execute(text("SELECT pg_backend_pid()")).scalar()
        _write_sale(t1, ORDER_A, qty=2)
        refresh_rollup(t1, {(MLA, DAY)})  # T1 holds its refresh, uncommitted

        def second_worker() -> None:
            try:
                _write_sale(t2, ORDER_B, qty=3)
                refresh_rollup(t2, {(MLA, DAY)})
                t2.commit()
            except Exception as exc:  # noqa: BLE001 -- surfaced by the assertion below
                errors.append(exc)
                t2.rollback()

        worker = threading.Thread(target=second_worker)
        worker.start()
        # T2 is provably waiting on T1 before T1 commits: on the advisory
        # lock (before its read) with the fix, on T1's row (after its read)
        # without it.
        _wait_until_blocked(engine, waiter_pid=t2_pid, holder_pid=t1_pid, advisory=locked)
        t1.commit()
        worker.join(timeout=30)
        assert not worker.is_alive(), "second refresh never finished (deadlock?)"
        assert errors == []

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT units, orders, total_gauss FROM ml_product_daily_metrics WHERE mla = :mla AND day = :day"),
                {"mla": MLA, "day": DAY},
            ).one()
        if locked:
            assert (row.units, row.orders, row.total_gauss) == (5, 2, Decimal("50.00"))
        else:
            # The lost update the lock exists to prevent: only B survives.
            assert (row.units, row.orders, row.total_gauss) == (3, 1, Decimal("30.00"))
    finally:
        t1.close()
        if worker is not None and worker.is_alive() and t2_pid is not None:
            # T2 is stuck and its session belongs to the worker thread: kill
            # its backend instead of touching the session from here, so the
            # cleanup below cannot block on locks T2 still holds.
            with engine.connect() as killer:
                killer.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": t2_pid})
            worker.join(timeout=10)
        else:
            t2.close()
        with engine.begin() as conn:
            for stmt in (
                "DELETE FROM ml_product_daily_metrics WHERE mla = :mla",
                "DELETE FROM ml_group_metrics WHERE group_key IN (:ka, :kb)",
                "DELETE FROM ml_order_metrics WHERE order_id IN (:a, :b)",
                "DELETE FROM ml_order_item_costos WHERE order_id IN (:a, :b)",
                "DELETE FROM ml_order_items_ops WHERE order_id IN (:a, :b)",
                "DELETE FROM ml_orders_ops WHERE order_id IN (:a, :b)",
            ):
                conn.execute(
                    text(stmt),
                    {"mla": MLA, "a": ORDER_A, "b": ORDER_B, "ka": f"o:{ORDER_A}", "kb": f"o:{ORDER_B}"},
                )

"""Migration `20261110_pedido_lineas_facturadas_importe` (sell-in-sell-out T3g-1):
chain, columns + CHECKs, backfill parity with the live reconcile, downgrade and
lock handling on a real Postgres.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import CheckViolation, LockNotAvailable
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.services.erp_matching_service import reconciliar_lineas_facturadas
from tests.services.erp_matching._schema import USD, filas, lf_schema, linea, nota_credito, pedido_con_factura

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261110_pedido_lineas_facturadas_importe"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_COLUMNS = (
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = 'pedido_compra_lineas_facturadas' "
    "AND column_name IN ('importe_neto', 'moneda')"
)


def _module():
    spec = importlib.util.spec_from_file_location("pedido_lineas_facturadas_importe_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _columns(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(_COLUMNS))}


def _seed(conn) -> None:
    """Pedido 1: same-currency credit note, mixed item, clamp item. Pedido 3: USD lines on an ARS header."""
    pedido_con_factura(conn)
    nota_credito(conn)
    linea(conn, 1, 100, 501, "10", "100.005", 1)
    linea(conn, 2, 200, 501, "1", "100", 1)
    linea(conn, 3, 100, 502, "4", "5", USD)
    linea(conn, 4, 200, 502, "1", "0.10", 1)
    linea(conn, 5, 100, 503, "2", "10", USD)
    linea(conn, 6, 200, 503, "1", "30", USD)
    pedido_con_factura(conn, pedido_id=3, ct=300, curr=1)
    linea(conn, 7, 300, 501, "2", "7.25", USD)


def _snapshot_v1(conn) -> None:
    # The quantities 20261104 / the reconcile already stored before this revision.
    conn.execute(
        text(
            "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) "
            "VALUES (1, 501, 9), (1, 502, 3), (1, 503, 1), (3, 501, 2)"
        )
    )


@pytest.fixture
def v1() -> Iterator[Engine]:
    with lf_schema(con_importe=False) as engine:
        yield engine


def test_this_revision_chains_on_the_sell_out_triggers_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261109_sell_out_triggers"


@pytest.mark.postgres
def test_upgrade_adds_the_columns_and_backfills_what_the_reconcile_computes(v1):
    with v1.begin() as conn:
        _seed(conn)
        _snapshot_v1(conn)

    _step(v1, "upgrade")

    esperado = [
        (1, 501, 9, "900.05", "ARS"),
        (1, 502, 3, None, None),
        (1, 503, 1, "0.00", "USD"),
        (3, 501, 2, "14.50", "USD"),
    ]
    assert filas(v1) == esperado
    # Parity: the live reconcile over the same mirror stores exactly the same rows.
    with lf_schema() as live:
        with live.begin() as conn:
            _seed(conn)
        with Session(live) as session:
            reconciliar_lineas_facturadas(session)
            session.commit()
        assert filas(live) == esperado


@pytest.mark.postgres
@pytest.mark.parametrize(
    "valores", ["importe_neto = -0.01", "moneda = 'EUR'"], ids=["negative-amount", "unknown-currency"]
)
def test_upgrade_installs_the_checks(v1, valores):
    with v1.begin() as conn:
        _seed(conn)
        _snapshot_v1(conn)
    _step(v1, "upgrade")

    with pytest.raises(IntegrityError) as caught, v1.begin() as conn:
        conn.execute(text(f"UPDATE pedido_compra_lineas_facturadas SET {valores} WHERE item_id = 501"))
    assert isinstance(caught.value.orig, CheckViolation)


@pytest.mark.postgres
def test_downgrade_drops_both_columns_and_keeps_the_quantities(v1):
    with v1.begin() as conn:
        _seed(conn)
        _snapshot_v1(conn)
    _step(v1, "upgrade")
    assert _columns(v1) == {"importe_neto", "moneda"}

    _step(v1, "downgrade")

    assert _columns(v1) == set()
    with v1.connect() as conn:
        assert conn.execute(text("SELECT SUM(cantidad) FROM pedido_compra_lineas_facturadas")).scalar() == 15


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_behind_an_open_writer_it_fails_fast_instead_of_blocking_the_table(v1, step):
    if step == "downgrade":
        _step(v1, "upgrade")
    with v1.connect() as sync:
        tx = sync.begin()
        sync.exec_driver_sql("LOCK TABLE pedido_compra_lineas_facturadas IN ROW EXCLUSIVE MODE")
        try:
            with v1.connect() as conn:
                conn.exec_driver_sql("SET statement_timeout = '20s'")  # bounds the test if it does block
                ctx = MigrationContext.configure(conn)
                with pytest.raises(OperationalError) as caught:
                    with ctx.begin_transaction(), Operations.context(ctx):
                        getattr(_module(), step)()
        finally:
            tx.rollback()
    assert isinstance(caught.value.orig, LockNotAvailable)


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(v1, step):
    if step == "downgrade":
        _step(v1, "upgrade")
    with v1.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '42s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"

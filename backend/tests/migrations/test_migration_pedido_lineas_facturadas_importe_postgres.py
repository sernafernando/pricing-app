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
from tests.services.erp_matching._schema import (
    USD,
    documento,
    filas,
    lf_schema,
    linea,
    nota_credito,
    pedido_con_factura,
)

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


def _imputacion(conn, id_: int, origen_tipo: str, origen_id: int, destino_tipo: str, destino_id: int, **extra) -> None:
    conn.execute(
        text(
            "INSERT INTO imputaciones (id, origen_tipo, origen_id, destino_tipo, destino_id, es_reversal, "
            "reimputada_desde_id) VALUES (:id, :ot, :oi, :dt, :di, :rev, :desde)"
        ),
        {
            "id": id_,
            "ot": origen_tipo,
            "oi": origen_id,
            "dt": destino_tipo,
            "di": destino_id,
            "rev": extra.get("es_reversal", False),
            "desde": extra.get("reimputada_desde_id"),
        },
    )


def _seed(conn) -> None:
    """Every document path of the service's _DOCUMENTOS_SQL.

    Pedido 1: same-currency credit note imputed to the pedido, mixed item, clamp item.
    Pedido 3: USD lines on an ARS header.
    Pedido 6: corrected from 5, corrected from 4 (both without a link); the credit note
      is frozen on the grand-ancestor 4, reached only through the recursive chain.
    Pedido 7: credit note imputed to the invoice (`factura_erp`), not the pedido.
    Pedido 8: local credit note (`nota_credito_local` → its ct_transaction_id), plus an
      ERP credit note whose imputación was reversed (does not count).
    """
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

    conn.execute(
        text(
            "INSERT INTO pedidos_compra (id, ct_transaction_id, corregido_desde_id) "
            "VALUES (4, NULL, NULL), (5, NULL, 4), (6, 600, 5)"
        )
    )
    documento(conn, 600)
    documento(conn, 610, signo=-1, clasificacion="NC")
    _imputacion(conn, 2, "nota_credito_erp", 610, "pedido_compra", 4)
    linea(conn, 8, 600, 601, "5", "20", 1)
    linea(conn, 9, 610, 601, "1", "20", 1)

    pedido_con_factura(conn, pedido_id=7, ct=700, curr=USD)
    documento(conn, 710, signo=-1, clasificacion="NC", curr=USD)
    _imputacion(conn, 3, "nota_credito_erp", 710, "factura_erp", 700)
    linea(conn, 10, 700, 701, "3", "1.10", USD)
    linea(conn, 11, 710, 701, "1", "1.10", USD)

    pedido_con_factura(conn, pedido_id=8, ct=800)
    documento(conn, 810, signo=-1, clasificacion="NC")
    conn.execute(text("INSERT INTO notas_credito_local (id, ct_transaction_id) VALUES (50, 810)"))
    _imputacion(conn, 4, "nota_credito_local", 50, "pedido_compra", 8)
    documento(conn, 820, signo=-1, clasificacion="NC")
    _imputacion(conn, 5, "nota_credito_erp", 820, "pedido_compra", 8)
    _imputacion(conn, 6, "nota_credito_erp", 820, "pedido_compra", 8, es_reversal=True, reimputada_desde_id=5)
    linea(conn, 12, 800, 801, "6", "7", 1)
    linea(conn, 13, 810, 801, "2", "7", 1)
    linea(conn, 14, 820, 801, "1", "7", 1)


def _snapshot_v1(conn) -> None:
    # The quantities 20261104 / the reconcile already stored before this revision.
    conn.execute(
        text(
            "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) "
            "VALUES (1, 501, 9), (1, 502, 3), (1, 503, 1), (3, 501, 2), (6, 601, 4), (7, 701, 2), (8, 801, 4)"
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
        (6, 601, 4, "80.00", "ARS"),
        (7, 701, 2, "2.20", "USD"),
        (8, 801, 4, "28.00", "ARS"),
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
        assert conn.execute(text("SELECT SUM(cantidad) FROM pedido_compra_lineas_facturadas")).scalar() == 25


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

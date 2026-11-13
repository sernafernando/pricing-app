"""Migration `20261114_sell_in_facturas_elegidas` (sell in varias facturas S3-S5): creates the per-invoice snapshot
(backfilled from the ERP mirror before its queue triggers exist) and the tactical lines' pick of invoices; the
downgrade drops both. On a real Postgres, over the ERP stub tables of the snapshot tests."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.services.erp_matching._schema import ERP_DDL
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261114_sell_in_facturas_elegidas"


def _module(revision: str = _REVISION):
    spec = importlib.util.spec_from_file_location(f"{revision}_m", os.path.join(_VERSIONS, f"{revision}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STUBS = [
    ERP_DDL,
    "CREATE TABLE tacticals (id BIGINT PRIMARY KEY)",
    "CREATE TABLE encolados (pedido_id BIGINT NOT NULL)",
    # Stand-in for the live queue function: records which operation a row change would queue.
    """
CREATE FUNCTION sell_in_bono_enqueue_linea() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO encolados VALUES (COALESCE(NEW.pedido_id, OLD.pedido_id));
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    # Operation 1: invoices 100 (501 x3) and 300 (501 x4, 502 x2), and a credit note 500 on the whole operation.
    "INSERT INTO pedidos_compra (id, ct_transaction_id) VALUES (1, 100)",
    "INSERT INTO pedido_compra_facturas (pedido_id, ct_transaction_id) VALUES (1, 100), (1, 300)",
    "INSERT INTO v_facturas_compra_vigentes (ct_transaction, sd_plusorminus, clasificacion) "
    "VALUES (100, 1, 'FACTURA'), (300, 1, 'FACTURA'), (500, -1, 'NC')",
    "INSERT INTO imputaciones (id, origen_tipo, origen_id, destino_tipo, destino_id) "
    "VALUES (1, 'nota_credito_erp', 500, 'pedido_compra', 1)",
    "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, item_id, it_qty) "
    "VALUES (1, 100, 501, 3), (2, 300, 501, 4), (3, 300, 502, 2), (4, 500, 502, 1)",
    "INSERT INTO tacticals VALUES (1)",
]


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("facturas_eleg", [], _STUBS) as engine:
        yield engine


def _filas(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql))]


def test_this_revision_chains_on_the_applied_totals_gate() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261114_sell_in_cubre_totales_aplicados"
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {rev.revision for rev in script.iterate_revisions(heads[0], "base")}


@pytest.mark.postgres
def test_upgrade_backfills_the_per_invoice_split_without_queueing(before) -> None:
    _step(before, "upgrade")

    assert _filas(
        before,
        "SELECT ct_transaction_id, item_id, cantidad FROM pedido_compra_lineas_facturadas_ct "
        "ORDER BY ct_transaction_id NULLS LAST, item_id",
    ) == [(100, 501, 3), (300, 501, 4), (300, 502, 2), (None, 502, -1)]
    assert _filas(before, "SELECT pedido_id FROM encolados") == []  # the backfill queues nothing


@pytest.mark.postgres
def test_after_upgrade_a_per_invoice_change_queues_its_operation(before) -> None:
    _step(before, "upgrade")

    with before.begin() as conn:
        conn.execute(text("UPDATE pedido_compra_lineas_facturadas_ct SET cantidad = 5 WHERE ct_transaction_id = 100"))
        conn.execute(text("UPDATE pedido_compra_lineas_facturadas_ct SET cantidad = 5 WHERE ct_transaction_id = 100"))

    assert _filas(before, "SELECT pedido_id FROM encolados") == [(1,)]  # a no-op update queues nothing


@pytest.mark.postgres
def test_upgrade_creates_the_pick_table(before) -> None:
    _step(before, "upgrade")

    with before.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tactical_linea_facturas (tactical_id, tactical_linea, ct_transaction_id) VALUES (1, 1, 100)"
            )
        )
    with pytest.raises(IntegrityError):
        with before.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tactical_linea_facturas (tactical_id, tactical_linea, ct_transaction_id) VALUES (1, 1, 100)"
                )
            )
    with pytest.raises(IntegrityError):
        with before.begin() as conn:
            conn.execute(
                text("INSERT INTO pedido_compra_lineas_facturadas_ct (pedido_id, item_id, cantidad) VALUES (1, 502, 3)")
            )


@pytest.mark.postgres
def test_downgrade_drops_both_tables(before) -> None:
    _step(before, "upgrade")
    _step(before, "downgrade")

    for tabla in ("pedido_compra_lineas_facturadas_ct", "tactical_linea_facturas"):
        assert _filas(before, f"SELECT to_regclass('{tabla}')") == [(None,)]


def test_the_frozen_triggers_are_the_live_ones() -> None:
    from app.services.sell_in import bono_queue

    assert [_norm(s) for s in _module().TRIGGERS_UP] == [_norm(s) for s in bono_queue.LINEAS_CT_SQL]


def test_the_frozen_backfill_is_the_live_reconcile_origin() -> None:
    from app.services import erp_matching_service

    vivo = erp_matching_service._LINEAS_CT_ORIGEN_SQL.format(scope_pedido="1 = 1")
    assert _norm(_module().ORIGEN_SQL) == _norm(vivo)


def _norm(sql: str) -> str:
    return " ".join(sql.split())

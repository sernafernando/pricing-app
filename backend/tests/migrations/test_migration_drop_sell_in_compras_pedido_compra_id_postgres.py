"""Migration `20261217_drop_sell_in_compras_pedido_compra_id` (T28): drops the legacy `sell_in_compras.pedido_compra_id`
column, which nothing reads or writes since #1809 (a purchase's operations live in `sell_in_compra_pedidos`); its
downgrade puts the column back empty, on a real Postgres. The tables are stubs with the columns involved."""

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

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261217_drop_sell_in_compras_pedido_compra_id"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_STUBS = [
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",
    "INSERT INTO pedidos_compra VALUES (15), (16)",
    """CREATE TABLE sell_in_compras (
        id BIGSERIAL PRIMARY KEY,
        pedido_compra_id BIGINT REFERENCES pedidos_compra(id) ON DELETE SET NULL,
        descripcion TEXT
    )""",
    "INSERT INTO sell_in_compras (id, pedido_compra_id, descripcion) VALUES "
    "(1, 15, 'vieja'), (2, NULL, 'nueva'), (3, 16, 'ya linkeada')",
    """CREATE TABLE sell_in_compra_pedidos (
        id BIGSERIAL PRIMARY KEY,
        compra_id BIGINT NOT NULL REFERENCES sell_in_compras(id) ON DELETE CASCADE,
        pedido_compra_id BIGINT NOT NULL REFERENCES pedidos_compra(id),
        UNIQUE (compra_id, pedido_compra_id)
    )""",
    # Purchase 1's operation is only in the legacy column; purchase 3 already has its link.
    "INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id) VALUES (3, 16)",
]
_LINKS = "SELECT compra_id, pedido_compra_id FROM sell_in_compra_pedidos ORDER BY compra_id, pedido_compra_id"
_COLUMN = (
    "SELECT data_type, is_nullable FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = 'sell_in_compras' AND column_name = 'pedido_compra_id'"
)
_FK_RULE = """
    SELECT rc.delete_rule, ccu.table_name, ccu.column_name
    FROM information_schema.key_column_usage kcu
    JOIN information_schema.referential_constraints rc
      ON rc.constraint_name = kcu.constraint_name AND rc.constraint_schema = kcu.constraint_schema
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = rc.unique_constraint_name AND ccu.constraint_schema = rc.unique_constraint_schema
    WHERE kcu.table_schema = current_schema() AND kcu.table_name = 'sell_in_compras'
      AND kcu.column_name = 'pedido_compra_id'
"""


def _module():
    spec = importlib.util.spec_from_file_location("drop_sell_in_compras_pedido_compra_id_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_drop_pedido", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_split_permission_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261216_sell_out_repartir_permiso"
    assert len(script.get_heads()) == 1


def test_the_orm_no_longer_maps_the_column() -> None:
    from app.models.sell_in import SellInCompra

    assert "pedido_compra_id" not in SellInCompra.__table__.columns


@pytest.mark.postgres
def test_upgrade_drops_the_column_keeps_the_rows_and_is_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMN)).all() == []
        assert conn.execute(text("SELECT id, descripcion FROM sell_in_compras ORDER BY id")).all() == [
            (1, "vieja"),
            (2, "nueva"),
            (3, "ya linkeada"),
        ]


@pytest.mark.postgres
def test_upgrade_first_links_an_operation_found_only_in_the_column_without_duplicating(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")

    with before.connect() as conn:
        assert conn.execute(text(_LINKS)).all() == [(1, 15), (3, 16)]


@pytest.mark.postgres
def test_downgrade_puts_the_column_back_empty_with_its_foreign_key_and_is_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert tuple(conn.execute(text(_COLUMN)).one()) == ("bigint", "YES")
        assert [tuple(r) for r in conn.execute(text(_FK_RULE))] == [("SET NULL", "pedidos_compra", "id")]
        # The data is lost: the purchases' operations are in sell_in_compra_pedidos.
        assert conn.execute(text("SELECT id, pedido_compra_id FROM sell_in_compras ORDER BY id")).all() == [
            (1, None),
            (2, None),
            (3, None),
        ]


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step) -> None:
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '42s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"

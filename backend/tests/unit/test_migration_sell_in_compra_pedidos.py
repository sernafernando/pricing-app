"""Migration `20261102_sell_in_compra_pedidos`: the link between a sell in and
its Compras operations (`pedidos_compra`), filled from the old single column.

Runs `20261024_sell_in_tables` and then this migration inside a throwaway
schema of the Postgres test DB, next to bare stand-ins of the referenced
tables, and proves the UNIQUE/CASCADE rules and the backfill at the database.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.database import Base
from app.models.sell_in import SellInCompraPedido

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _BACKEND_ROOT / "alembic" / "versions"
_REVISION = "20261102_sell_in_compra_pedidos"
_TABLE = "sell_in_compra_pedidos"

_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",
    "CREATE TABLE productos_erp (item_id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO pedidos_compra VALUES (900), (901)",
]

_INSERT_COMPRA = (
    "INSERT INTO sell_in_compras (pedido_compra_id, fecha_compra, moneda, monto_total, usuario_id) "
    "VALUES (:pedido, DATE '2026-10-01', 'ARS', 1000.00, 7) RETURNING id"
)
_INSERT_LINK = "INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id) VALUES (:compra, :pedido)"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _module(revision: str):
    spec = importlib.util.spec_from_file_location(f"{revision}_migration", _VERSIONS / f"{revision}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(engine: Engine, revision: str, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(revision), step)()


class TestMigrationGraph:
    def test_single_head_descends_from_this_revision(self) -> None:
        scripts = _script_directory()
        heads = scripts.get_heads()
        assert len(heads) == 1
        assert _REVISION in {rev.revision for rev in scripts.iterate_revisions(heads[0], "base")}

    def test_chains_on_the_previous_head(self) -> None:
        assert _script_directory().get_revision(_REVISION).down_revision == "20261101_combo_componentes"


def _throwaway_schema(prefix: str) -> tuple[Engine, Engine, str]:
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_schema()")).scalar() == schema
        for statement in _STUBS:
            conn.execute(text(statement))
    return admin, engine, schema


def _drop(admin: Engine, engine: Engine, schema: str) -> None:
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


@pytest.fixture()
def before() -> Iterator[Engine]:
    """Schema at the previous sell-in state: the tables exist, the link table does not."""
    admin, engine, schema = _throwaway_schema("si_cp_mig")
    try:
        _run(engine, "20261024_sell_in_tables", "upgrade")
        yield engine
    finally:
        _drop(admin, engine, schema)


@pytest.fixture()
def engine(before: Engine) -> Engine:
    _run(before, _REVISION, "upgrade")
    return before


def _links(engine: Engine) -> list[tuple[int, int]]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT compra_id, pedido_compra_id FROM {_TABLE} ORDER BY compra_id"))
        return [tuple(r) for r in rows]


def _new_compra(conn, pedido: int | None) -> int:
    return conn.execute(text(_INSERT_COMPRA), {"pedido": pedido}).scalar_one()


_CATALOG = {
    "columns": (
        "SELECT column_name, data_type, numeric_precision, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = :t"
    ),
    "constraints": (
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE connamespace = current_schema()::regnamespace AND conrelid::regclass::text = :t"
    ),
    "indexes": (
        "SELECT indexname, replace(indexdef, schemaname || '.', '') FROM pg_indexes "
        "WHERE schemaname = current_schema() AND tablename = :t"
    ),
}


def _catalog(engine: Engine) -> dict[str, set[tuple]]:
    with engine.connect() as conn:
        return {kind: {tuple(r) for r in conn.execute(text(sql), {"t": _TABLE})} for kind, sql in _CATALOG.items()}


@pytest.mark.postgres
class TestSellInCompraPedidosMigration:
    def test_backfill_copies_every_set_column_and_nothing_else(self, before: Engine) -> None:
        with before.begin() as conn:
            con_900 = _new_compra(conn, 900)
            sin = _new_compra(conn, None)
            otra_900 = _new_compra(conn, 900)  # one operation referenced by two sell ins is kept
            con_901 = _new_compra(conn, 901)

        _run(before, _REVISION, "upgrade")

        assert _links(before) == [(con_900, 900), (otra_900, 900), (con_901, 901)]
        assert sin not in {compra for compra, _ in _links(before)}

    def test_schema_matches_the_orm_model(self, engine: Engine) -> None:
        from tests.conftest import _restore_pristine_pg_types

        table = Base.metadata.tables[_TABLE]
        found = {column: column.type for column in table.columns}
        admin, orm, schema = _throwaway_schema("si_cp_orm")
        try:
            _run(orm, "20261024_sell_in_tables", "upgrade")
            _restore_pristine_pg_types([table])
            try:
                Base.metadata.create_all(bind=orm, tables=[table])
            finally:
                for column, column_type in found.items():
                    column.type = column_type
            migrated, declared = _catalog(engine), _catalog(orm)
        finally:
            _drop(admin, orm, schema)
        for kind in _CATALOG:
            assert migrated[kind] == declared[kind], kind
        assert {c.name for c in SellInCompraPedido.__table__.columns} == {r[0] for r in migrated["columns"]}

    def test_the_pair_is_unique_but_an_operation_can_serve_several_sell_ins(self, engine: Engine) -> None:
        with engine.begin() as conn:
            a, b = _new_compra(conn, None), _new_compra(conn, None)
            conn.execute(text(_INSERT_LINK), {"compra": a, "pedido": 900})
            conn.execute(text(_INSERT_LINK), {"compra": a, "pedido": 901})
            conn.execute(text(_INSERT_LINK), {"compra": b, "pedido": 900})
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(_INSERT_LINK), {"compra": a, "pedido": 900})

    def test_deleting_the_sell_in_removes_its_links(self, engine: Engine) -> None:
        with engine.begin() as conn:
            compra = _new_compra(conn, 900)
            conn.execute(text(_INSERT_LINK), {"compra": compra, "pedido": 900})
            conn.execute(text("DELETE FROM sell_in_compras WHERE id = :i"), {"i": compra})
        assert _links(engine) == []

    def test_deleting_the_operation_removes_the_link_and_clears_the_column(self, engine: Engine) -> None:
        with engine.begin() as conn:
            compra = _new_compra(conn, 900)
            conn.execute(text(_INSERT_LINK), {"compra": compra, "pedido": 900})
            conn.execute(text("DELETE FROM pedidos_compra WHERE id = 900"))
            column = conn.execute(
                text("SELECT pedido_compra_id FROM sell_in_compras WHERE id = :i"), {"i": compra}
            ).scalar_one()
        assert _links(engine) == []
        assert column is None

    def test_downgrade_drops_the_table_and_keeps_the_column(self, engine: Engine) -> None:
        with engine.begin() as conn:
            compra = _new_compra(conn, 900)
            conn.execute(text(_INSERT_LINK), {"compra": compra, "pedido": 900})

        _run(engine, _REVISION, "downgrade")

        with engine.connect() as conn:
            assert conn.execute(text(f"SELECT to_regclass('{_TABLE}')")).scalar() is None
            column = conn.execute(
                text("SELECT pedido_compra_id FROM sell_in_compras WHERE id = :i"), {"i": compra}
            ).scalar_one()
        assert column == 900

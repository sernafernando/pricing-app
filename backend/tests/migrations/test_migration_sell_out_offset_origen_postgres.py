"""Migration `20261111_sell_out_offset_origen` (sell-in-sell-out T15): the nullable,
unique `sell_out_campanas.offset_origen_id` FK to `offsets_ganancia`, its
downgrade and lock handling on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import ForeignKeyViolation, LockNotAvailable, UniqueViolation
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261111_sell_out_offset_origen"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
# Stand-ins for the two tables as they are before this revision (only what it touches).
_STUBS = [
    "CREATE TABLE offsets_ganancia (id SERIAL PRIMARY KEY)",
    "CREATE TABLE sell_out_campanas (id BIGSERIAL PRIMARY KEY, nombre VARCHAR(200) NOT NULL)",
    "INSERT INTO offsets_ganancia (id) VALUES (1), (2)",
]
_COLUMN = (
    "SELECT is_nullable FROM information_schema.columns WHERE table_schema = current_schema() "
    "AND table_name = 'sell_out_campanas' AND column_name = 'offset_origen_id'"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_out_offset_origen_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _insert(engine: Engine, offset_id) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sell_out_campanas (nombre, offset_origen_id) VALUES ('C', :o)"), {"o": offset_id}
        )


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("so_offset_origen", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_invoiced_amount_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261110_pedido_lineas_facturadas_importe"
    assert len(script.get_heads()) == 1  # no divergent heads; a later revision may sit on top of this one


@pytest.mark.postgres
def test_upgrade_adds_a_nullable_column(before):
    _step(before, "upgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMN)).scalar() == "YES"
    _insert(before, None)
    _insert(before, None)  # many campaigns without a legacy offset


@pytest.mark.postgres
def test_upgrade_keeps_the_campaigns_already_there_with_no_origin(before):
    with before.begin() as conn:
        conn.execute(text("INSERT INTO sell_out_campanas (nombre) VALUES ('a'), ('b'), ('c')"))
    _step(before, "upgrade")
    with before.connect() as conn:
        rows = conn.execute(text("SELECT nombre, offset_origen_id FROM sell_out_campanas ORDER BY id")).all()
    assert rows == [("a", None), ("b", None), ("c", None)]


@pytest.mark.postgres
def test_upgrade_allows_one_campaign_per_offset(before):
    _step(before, "upgrade")
    _insert(before, 1)

    with pytest.raises(IntegrityError) as caught:
        _insert(before, 1)
    assert isinstance(caught.value.orig, UniqueViolation)
    _insert(before, 2)


@pytest.mark.postgres
def test_upgrade_references_the_offset_and_clears_it_when_the_offset_is_deleted(before):
    _step(before, "upgrade")
    with pytest.raises(IntegrityError) as caught:
        _insert(before, 99)
    assert isinstance(caught.value.orig, ForeignKeyViolation)

    _insert(before, 1)
    with before.begin() as conn:
        conn.execute(text("DELETE FROM offsets_ganancia WHERE id = 1"))
        assert conn.execute(text("SELECT offset_origen_id FROM sell_out_campanas")).all() == [(None,)]


@pytest.mark.postgres
def test_downgrade_drops_the_column_and_is_idempotent(before):
    _step(before, "upgrade")
    _insert(before, 1)

    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMN)).scalar() is None
        assert conn.execute(text("SELECT COUNT(*) FROM sell_out_campanas")).scalar() == 1


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_behind_an_open_writer_it_fails_fast_instead_of_blocking_the_table(before, step):
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as writer:
        tx = writer.begin()
        writer.exec_driver_sql("LOCK TABLE sell_out_campanas IN ROW EXCLUSIVE MODE")
        try:
            with before.connect() as conn:
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
def test_it_restores_the_lock_timeout_the_transaction_had(before, step):
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '42s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"

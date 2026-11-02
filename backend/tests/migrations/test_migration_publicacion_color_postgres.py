"""Migration `20261229_publicacion_color` (seleccion-por-publicacion S3): the per-team ML color of one publication,
and the downgrade that refuses while a publication is painted, on a real Postgres. `producto_color` is not touched
(the migration never names it)."""

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
from sqlalchemy.exc import IntegrityError, InternalError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261229_publicacion_color.py")
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE equipo (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO equipo VALUES (1), (2)",
]
_TABLA = "SELECT to_regclass('publicacion_color') IS NOT NULL"


def _module():
    spec = importlib.util.spec_from_file_location("publicacion_color_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _paint(engine: Engine, equipo_id: int = 1, item_id: str = "MLA1", color: str = "rojo") -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO publicacion_color (equipo_id, item_id, color_ml, updated_by) VALUES (:e, :i, :c, 7)"),
            {"e": equipo_id, "i": item_id, "c": color},
        )


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("pub_color", [], _STUBS) as engine:
        yield engine


@pytest.fixture
def after(before) -> Engine:
    _step(before, "upgrade")
    return before


def test_this_revision_chains_on_the_sell_out_programs() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("20261229_publicacion_color")
    assert revision is not None
    assert revision.down_revision == "20261225_sell_out_programas"


@pytest.mark.postgres
def test_upgrade_creates_one_color_per_team_and_publication_and_runs_twice(after) -> None:
    _step(after, "upgrade")  # idempotent
    _paint(after, 1, "MLA1")
    _paint(after, 2, "MLA1", "azul")  # another team paints the same publication
    with pytest.raises(IntegrityError):
        _paint(after, 1, "MLA1", "verde")
    with pytest.raises(IntegrityError):
        _paint(after, 9, "MLA2")  # no such team


@pytest.mark.postgres
def test_downgrade_refuses_while_a_publication_is_painted_and_changes_nothing(after) -> None:
    _paint(after)
    with pytest.raises(InternalError, match="publicacion_color has painted publications"):
        _step(after, "downgrade")
    with after.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM publicacion_color")).scalar() == 1


@pytest.mark.postgres
def test_downgrade_with_nothing_painted_drops_the_table_and_runs_twice(after) -> None:
    _step(after, "downgrade")
    _step(after, "downgrade")
    with after.connect() as conn:
        assert conn.execute(text(_TABLA)).scalar() is False


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step) -> None:
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '17s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "17s"

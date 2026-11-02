"""Migration `20261225_sell_out_programas` (campaign system, slice A, S1): the program that groups sell-out
campaigns (`sell_out_programas`) and each campaign's `programa_id`, and the downgrade, on a real Postgres.

The "before" world is built by the real earlier sell-out migrations (not the ORM, which already declares this
revision's schema), next to bare stand-ins of the tables they reference."""

from __future__ import annotations

import importlib.util
import os
import re
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261225_sell_out_programas"
_EARLIER = (
    "20261105_sell_out_campanas",
    "20261108_sell_out_consumos",
    "20261111_sell_out_offset_origen",
    "20261207_sell_out_campana_items",
    "20261214_sell_out_monto_total",
)
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE offset_grupos (id INTEGER PRIMARY KEY)",
    "CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)",
    "CREATE TABLE roles (id SERIAL PRIMARY KEY, codigo VARCHAR(50) UNIQUE)",
    "CREATE TABLE permisos (id SERIAL PRIMARY KEY, codigo VARCHAR(100) UNIQUE, nombre TEXT, descripcion TEXT, "
    "categoria TEXT, orden INTEGER, es_critico BOOLEAN, created_at TIMESTAMPTZ)",
    "CREATE TABLE roles_permisos_base (rol_id INTEGER, permiso_id INTEGER, PRIMARY KEY (rol_id, permiso_id))",
    "CREATE TABLE usuarios_permisos_override (usuario_id INTEGER, permiso_id INTEGER)",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO roles (codigo) VALUES ('ADMIN')",
]
_CAMPANAS = "SELECT id, nombre, estado, monto_unit, updated_at FROM sell_out_campanas ORDER BY id"
_COLUMNA = (
    "SELECT data_type, is_nullable FROM information_schema.columns WHERE table_schema = current_schema() "
    "AND table_name = 'sell_out_campanas' AND column_name = 'programa_id'"
)
_TABLA = "SELECT to_regclass('sell_out_programas') IS NOT NULL"


def _module(revision: str = _REVISION):
    spec = importlib.util.spec_from_file_location(f"{revision}_migration", os.path.join(_VERSIONS, f"{revision}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str, revision: str = _REVISION) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(revision), step)()


def _build(engine: Engine) -> None:
    for revision in _EARLIER:
        _step(engine, "upgrade", revision)


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("so_programas", [], _STUBS, after=_build) as engine:
        yield engine


@pytest.fixture
def after(before) -> Engine:
    _step(before, "upgrade")
    return before


def _campana(engine: Engine, nombre: str = "MARCA PROG 24", **cols) -> int:
    names = "".join(f", {k}" for k in cols)
    params = "".join(f", :{k}" for k in cols)
    with engine.begin() as conn:
        return conn.execute(
            text(
                f"INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, moneda, "
                f"usuario_id{names}) VALUES (:n, '2026-11-01', '2026-11-30', 'por_unidad', 10, 'ARS', 7{params}) "
                "RETURNING id"
            ),
            {"n": nombre, **cols},
        ).scalar_one()


def _programa(engine: Engine, nombre: str = "MARCA PROG", **cols) -> int:
    names = "".join(f", {k}" for k in cols)
    params = "".join(f", :{k}" for k in cols)
    with engine.begin() as conn:
        return conn.execute(
            text(f"INSERT INTO sell_out_programas (nombre, usuario_id{names}) VALUES (:n, 7{params}) RETURNING id"),
            {"n": nombre, **cols},
        ).scalar_one()


def _scalar(engine: Engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def test_this_revision_chains_on_the_ml_ads_display_catalog() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261226_ml_ads_display_catalog"


@pytest.mark.postgres
def test_upgrade_leaves_existing_campaigns_untouched_and_without_a_program(before) -> None:
    _campana(before, "MARCA PROG 24")
    _campana(before, "Rebate Q4 2024", estado="anulada")
    with before.connect() as conn:
        antes = [tuple(r) for r in conn.execute(text(_CAMPANAS))]

    _step(before, "upgrade")

    with before.connect() as conn:
        assert [tuple(r) for r in conn.execute(text(_CAMPANAS))] == antes
        assert conn.execute(text(_COLUMNA)).one() == ("bigint", "YES")
        assert conn.execute(text("SELECT count(*) FROM sell_out_campanas WHERE programa_id IS NOT NULL")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM sell_out_programas")).scalar() == 0


@pytest.mark.postgres
def test_a_program_starts_active_and_its_state_is_a_closed_set(after) -> None:
    programa = _programa(after)
    assert _scalar(after, "SELECT estado FROM sell_out_programas WHERE id = :i", i=programa) == "activo"
    _programa(after, "Rebate", estado="archivado")
    with pytest.raises(IntegrityError):
        _programa(after, "TP-Link 2% noviembre", estado="borrado")


@pytest.mark.postgres
def test_a_program_name_is_unique_ignoring_case(after) -> None:
    _programa(after, "MARCA PROG")
    with pytest.raises(IntegrityError):
        _programa(after, "marca prog")


@pytest.mark.postgres
def test_a_campaign_points_at_an_existing_program_that_cannot_be_deleted_while_used(after) -> None:
    programa = _programa(after)
    campana = _campana(after, programa_id=programa)
    with pytest.raises(IntegrityError):
        _campana(after, programa_id=programa + 1000)
    with pytest.raises(IntegrityError):
        with after.begin() as conn:
            conn.execute(text("DELETE FROM sell_out_programas WHERE id = :i"), {"i": programa})
    with after.begin() as conn:
        conn.execute(text("UPDATE sell_out_campanas SET programa_id = NULL WHERE id = :c"), {"c": campana})
        conn.execute(text("DELETE FROM sell_out_programas WHERE id = :i"), {"i": programa})


@pytest.mark.postgres
def test_a_raw_sql_update_moves_the_program_updated_at(after) -> None:
    programa = _programa(after)
    antes = _scalar(after, "SELECT updated_at FROM sell_out_programas WHERE id = :i", i=programa)
    with after.begin() as conn:
        conn.execute(text("UPDATE sell_out_programas SET descripcion = 'Q' WHERE id = :i"), {"i": programa})
    assert _scalar(after, "SELECT updated_at FROM sell_out_programas WHERE id = :i", i=programa) > antes


def test_no_migration_creates_a_trigger_on_the_campaigns_but_updated_at() -> None:
    """Over EVERY revision (the statement triggers of 20261109 included, which the fixture below does not build):
    the only trigger any migration creates on `sell_out_campanas` keeps `updated_at`, so assigning a program
    queues no rebuild."""
    creados = set()
    for nombre in os.listdir(_VERSIONS):
        if nombre.endswith(".py"):
            with open(os.path.join(_VERSIONS, nombre), encoding="utf-8") as fh:
                fuente = fh.read()
            # 20261109 builds its statement triggers from a template: `_triggers("<name>", "<table>", ...)`.
            assert not re.search(r'_triggers\(\s*"\w+",\s*"sell_out_campanas"', fuente), nombre
            creados |= set(
                re.findall(r"CREATE (?:OR REPLACE )?TRIGGER\s+(\w+)[^;]*?\bON\s+sell_out_campanas\b", fuente)
            )
    assert creados == {"sell_out_campanas_updated_at"}


@pytest.mark.postgres
def test_the_migrated_campaigns_table_carries_only_the_updated_at_trigger(after) -> None:
    """On the schema these revisions build: the only trigger on `sell_out_campanas` keeps `updated_at`."""
    with after.connect() as conn:
        triggers = {
            r[0]
            for r in conn.execute(
                text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'sell_out_campanas'::regclass AND NOT tgisinternal")
            )
        }
    assert triggers == {"sell_out_campanas_updated_at"}


@pytest.mark.postgres
def test_downgrade_drops_the_column_and_the_table_and_is_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")  # idempotent
    _step(before, "downgrade")
    _step(before, "downgrade")  # idempotent
    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).all() == []
        assert conn.execute(text(_TABLA)).scalar() is False


@pytest.mark.postgres
@pytest.mark.parametrize("dato", ["programa", "asignada"])
def test_downgrade_refuses_while_a_program_exists(after, dato) -> None:
    """It fails loudly instead of deleting the operator's grouping."""
    programa = _programa(after)
    if dato == "asignada":
        _campana(after, programa_id=programa)

    with pytest.raises((InternalError, ProgrammingError, IntegrityError)) as caught:
        _step(after, "downgrade")
    assert _REVISION in str(caught.value)
    with after.connect() as conn:  # nothing was changed
        assert conn.execute(text(_COLUMNA)).all() != []
        assert conn.execute(text(_TABLA)).scalar() is True


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

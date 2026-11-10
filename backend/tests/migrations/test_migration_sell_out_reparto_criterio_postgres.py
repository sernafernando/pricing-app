"""Migration `20261107_sell_out_reparto_criterio` (tactical monto total, S2): each sell-out campaign's
`reparto_criterio`, how a `monto_total` campaign is split (NULL = by hand; `iguales`, `unidades`, `costo`), with no
backfill, and the downgrade, on a real Postgres.

The "before" world is built by the real earlier sell-out migrations (not the ORM, which already declares this
revision's schema), next to bare stand-ins of the tables they reference."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261107_sell_out_reparto_criterio"
_EARLIER = (
    "20261105_sell_out_campanas",
    "20261108_sell_out_consumos",
    "20261111_sell_out_offset_origen",
    "20261207_sell_out_campana_items",
    "20261214_sell_out_monto_total",
    "20261225_sell_out_programas",
    "20261230_sell_out_renovada_de",
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
_COLUMNA = (
    "SELECT data_type, character_maximum_length, is_nullable FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = 'sell_out_campanas' AND column_name = 'reparto_criterio'"
)
_CAMPANAS = "SELECT id, nombre, tipo, monto_unit, monto_total, updated_at FROM sell_out_campanas ORDER BY id"
_INSERT = (
    "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, monto_total, moneda, "
    "usuario_id) VALUES (:n, '2026-10-01', '2026-12-31', :t, :u, :m, 'ARS', 7)"
)


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
    with engine.begin() as conn:
        conn.execute(text(_INSERT), {"n": "Por unidad", "t": "por_unidad", "u": 10, "m": None})
        conn.execute(text(_INSERT), {"n": "Total notebooks", "t": "monto_total", "u": None, "m": 1200})


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("so_reparto_criterio", [], _STUBS, after=_build) as engine:
        yield engine


def _filas(engine: Engine) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(_CAMPANAS))]


def _ids(engine: Engine) -> list[int]:
    return [f[0] for f in _filas(engine)]


def _criterio(engine: Engine, campana_id: int, criterio: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sell_out_campanas SET reparto_criterio = :c WHERE id = :i"), {"c": criterio, "i": campana_id}
        )


def test_upgrade_adds_a_nullable_criterion_that_every_existing_campaign_leaves_empty(before) -> None:
    antes = _filas(before)
    _step(before, "upgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).one() == ("character varying", 16, "YES")
        assert (
            conn.execute(text("SELECT count(*) FROM sell_out_campanas WHERE reparto_criterio IS NOT NULL")).scalar()
            == 0
        )
    assert _filas(before) == antes  # no backfill, nothing else touched (updated_at included)


def test_upgrade_is_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).one() == ("character varying", 16, "YES")


@pytest.mark.parametrize("criterio", ["iguales", "unidades", "costo"])
def test_a_monto_total_campaign_takes_each_criterion(before, criterio: str) -> None:
    _step(before, "upgrade")
    _, total = _ids(before)
    _criterio(before, total, criterio)
    with before.connect() as conn:
        assert (
            conn.execute(text("SELECT reparto_criterio FROM sell_out_campanas WHERE id = :i"), {"i": total}).scalar()
            == criterio
        )


def test_an_unknown_criterion_is_refused(before) -> None:
    _step(before, "upgrade")
    _, total = _ids(before)
    with pytest.raises(IntegrityError, match="ck_sell_out_campanas_reparto_criterio"):
        _criterio(before, total, "manual")


def test_a_criterion_on_a_campaign_that_is_not_monto_total_is_refused(before) -> None:
    _step(before, "upgrade")
    por_unidad, _ = _ids(before)
    with pytest.raises(IntegrityError, match="ck_sell_out_campanas_reparto_criterio"):
        _criterio(before, por_unidad, "iguales")


def test_downgrade_drops_the_column(before) -> None:
    _step(before, "upgrade")
    _, total = _ids(before)
    _criterio(before, total, "unidades")
    _step(before, "downgrade")
    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).first() is None
    _step(before, "downgrade")  # idempotent

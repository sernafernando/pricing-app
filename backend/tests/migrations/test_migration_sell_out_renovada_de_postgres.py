"""Migration `20261230_sell_out_renovada_de` (Renovar programa, S4): each sell-out campaign's `renovada_de_id`, the
campaign it renews (nullable, FK to `sell_out_campanas` ON DELETE SET NULL, indexed, no backfill), and the downgrade,
on a real Postgres.

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
from sqlalchemy.exc import IntegrityError, InternalError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261230_sell_out_renovada_de"
_EARLIER = (
    "20261105_sell_out_campanas",
    "20261108_sell_out_consumos",
    "20261111_sell_out_offset_origen",
    "20261207_sell_out_campana_items",
    "20261214_sell_out_monto_total",
    "20261225_sell_out_programas",
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
    "SELECT data_type, is_nullable FROM information_schema.columns WHERE table_schema = current_schema() "
    "AND table_name = 'sell_out_campanas' AND column_name = 'renovada_de_id'"
)
_CAMPANAS = "SELECT id, nombre, estado, monto_unit, programa_id, updated_at FROM sell_out_campanas ORDER BY id"


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
        for nombre in ("Modelo Q4 2026", "Modelo Q1 2027"):
            conn.execute(
                text(
                    "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, moneda, "
                    "usuario_id) VALUES (:n, '2026-10-01', '2026-12-31', 'por_unidad', 10, 'ARS', 7)"
                ),
                {"n": nombre},
            )


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("so_renovada_de", [], _STUBS, after=_build) as engine:
        yield engine


def _filas(engine: Engine) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(_CAMPANAS))]


def _ids(engine: Engine) -> list[int]:
    return [f[0] for f in _filas(engine)]


def test_upgrade_adds_a_nullable_link_that_every_existing_campaign_leaves_empty(before) -> None:
    antes = _filas(before)
    _step(before, "upgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).one() == ("bigint", "YES")
        assert (
            conn.execute(text("SELECT count(*) FROM sell_out_campanas WHERE renovada_de_id IS NOT NULL")).scalar() == 0
        )
        indices = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'sell_out_campanas'"
            )
        ).scalars()
        assert "ix_sell_out_campanas_renovada_de_id" in set(indices)
    assert _filas(before) == antes  # no backfill, nothing else touched (updated_at included)


def test_upgrade_is_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).one() == ("bigint", "YES")


def test_the_link_must_name_a_campaign_and_deleting_it_clears_the_link(before) -> None:
    _step(before, "upgrade")
    original, copia = _ids(before)
    with pytest.raises(IntegrityError):
        with before.begin() as conn:
            conn.execute(text("UPDATE sell_out_campanas SET renovada_de_id = 999999 WHERE id = :c"), {"c": copia})
    with before.begin() as conn:
        conn.execute(
            text("UPDATE sell_out_campanas SET renovada_de_id = :o WHERE id = :c"), {"o": original, "c": copia}
        )
        conn.execute(text("DELETE FROM sell_out_campanas WHERE id = :o"), {"o": original})
    with before.connect() as conn:
        assert (
            conn.execute(text("SELECT renovada_de_id FROM sell_out_campanas WHERE id = :c"), {"c": copia}).scalar()
            is None
        )


def test_downgrade_refuses_while_a_campaign_is_linked_and_changes_nothing(before) -> None:
    _step(before, "upgrade")
    original, copia = _ids(before)
    with before.begin() as conn:
        conn.execute(
            text("UPDATE sell_out_campanas SET renovada_de_id = :o WHERE id = :c"), {"o": original, "c": copia}
        )
    antes = _filas(before)

    with pytest.raises(InternalError, match="renewal"):
        _step(before, "downgrade")
    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).one() == ("bigint", "YES")
    assert _filas(before) == antes


def test_downgrade_without_links_drops_the_column(before) -> None:
    _step(before, "upgrade")
    _step(before, "downgrade")
    with before.connect() as conn:
        assert conn.execute(text(_COLUMNA)).first() is None
    _step(before, "downgrade")  # idempotent

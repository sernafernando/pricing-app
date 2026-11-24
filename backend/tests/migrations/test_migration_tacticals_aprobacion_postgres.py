"""Migration `20261122_tacticals_aprobacion` (tacticals approval S1, S3, S7): the 'pendiente' state on tacticals and
their line engines, `aprobado_por` / `aprobado_at`, and the opt-in `tacticals.aprobar` permission granted to no role.
Existing tacticals and lines keep their state, with both columns NULL. On a real Postgres, over stub tables with the
previous CHECKs."""

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
_REVISION = "20261122_tacticals_aprobacion"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_CODIGO = "tacticals.aprobar"


def _linea(tabla: str) -> str:
    return (
        f"CREATE TABLE {tabla} (id BIGSERIAL PRIMARY KEY, estado VARCHAR(16) NOT NULL DEFAULT 'activa', "
        f"CONSTRAINT ck_{tabla}_estado CHECK (estado IN ('activa', 'anulada')))"
    )


_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7), (8)",
    "CREATE TABLE roles (id SERIAL PRIMARY KEY, codigo VARCHAR(50) UNIQUE)",
    "CREATE TABLE permisos (id SERIAL PRIMARY KEY, codigo VARCHAR(100) UNIQUE, nombre TEXT, descripcion TEXT, "
    "categoria TEXT, orden INTEGER, es_critico BOOLEAN, created_at TIMESTAMP)",
    "CREATE TABLE roles_permisos_base (rol_id INTEGER, permiso_id INTEGER, PRIMARY KEY (rol_id, permiso_id))",
    "CREATE TABLE usuarios_permisos_override (usuario_id INTEGER, permiso_id INTEGER, concedido BOOLEAN)",
    "INSERT INTO roles (codigo) VALUES ('SUPERADMIN'), ('ADMIN'), ('PRICING')",
    "CREATE TABLE tacticals (id BIGSERIAL PRIMARY KEY, estado VARCHAR(16) NOT NULL DEFAULT 'activo', "
    "CONSTRAINT ck_tacticals_estado CHECK (estado IN ('activo', 'anulado')))",
    _linea("sell_in_bonos_marca"),
    _linea("sell_in_compras"),
    _linea("sell_out_campanas"),
    "INSERT INTO tacticals (estado) VALUES ('activo'), ('anulado')",
    "INSERT INTO sell_in_bonos_marca (estado) VALUES ('activa'), ('anulada')",
    "INSERT INTO sell_in_compras (estado) VALUES ('activa')",
    "INSERT INTO sell_out_campanas (estado) VALUES ('anulada')",
    "CREATE TABLE offsets_ganancia (id SERIAL PRIMARY KEY, monto DOUBLE PRECISION)",
    "INSERT INTO offsets_ganancia (monto) VALUES (100), (-50)",
]
_LINEAS = ("sell_in_bonos_marca", "sell_in_compras", "sell_out_campanas")


def _step(engine: Engine, step: str) -> None:
    spec = importlib.util.spec_from_file_location("tacticals_aprobacion_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_aprobacion", [], _STUBS) as engine:
        yield engine


def _filas(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql))]


def test_this_revision_chains_on_the_single_previous_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261129_costo_si_compras_sospechosas"
    assert len(script.get_heads()) == 1
    assert len(_REVISION) <= 64


@pytest.mark.postgres
def test_existing_tacticals_and_lines_keep_their_state_with_no_approver(engine) -> None:
    _step(engine, "upgrade")

    assert _filas(engine, "SELECT estado, aprobado_por, aprobado_at FROM tacticals ORDER BY id") == [
        ("activo", None, None),
        ("anulado", None, None),
    ]
    assert _filas(engine, "SELECT estado FROM sell_in_bonos_marca ORDER BY id") == [("activa",), ("anulada",)]
    assert _filas(engine, "SELECT estado FROM sell_in_compras") == [("activa",)]
    assert _filas(engine, "SELECT estado FROM sell_out_campanas") == [("anulada",)]


@pytest.mark.postgres
def test_upgrade_accepts_pending_and_records_the_approver(engine) -> None:
    _step(engine, "upgrade")

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO tacticals (estado) VALUES ('pendiente')"))
        conn.execute(text("UPDATE tacticals SET aprobado_por = 8, aprobado_at = now() WHERE estado = 'activo'"))
        for tabla in _LINEAS:
            conn.execute(text(f"INSERT INTO {tabla} (estado) VALUES ('pendiente')"))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE tacticals SET aprobado_por = 999"))  # FK to usuarios
    for tabla, valor in (("tacticals", "borrado"), *((t, "borrada") for t in _LINEAS)):
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(f"INSERT INTO {tabla} (estado) VALUES ('{valor}')"))
    assert _filas(engine, "SELECT indexname FROM pg_indexes WHERE indexname = 'ix_tacticals_aprobado_por'")


@pytest.mark.postgres
def test_the_permission_is_seeded_once_and_granted_to_no_role(engine) -> None:
    _step(engine, "upgrade")
    _step(engine, "upgrade")  # idempotent

    assert _filas(engine, f"SELECT count(*) FROM permisos WHERE codigo = '{_CODIGO}'") == [(1,)]
    assert _filas(engine, "SELECT count(*) FROM roles_permisos_base") == [(0,)]
    assert _filas(engine, "SELECT count(*) FROM usuarios_permisos_override") == [(0,)]


@pytest.mark.postgres
def test_downgrade_refuses_while_something_is_pending(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO sell_out_campanas (estado) VALUES ('pendiente')"))

    with pytest.raises(InternalError, match="loads pending approval exist"):
        _step(engine, "downgrade")
    assert _filas(engine, f"SELECT count(*) FROM permisos WHERE codigo = '{_CODIGO}'") == [(1,)]


@pytest.mark.postgres
def test_downgrade_restores_the_previous_schema_and_removes_the_permission(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) "
                f"SELECT 8, id, true FROM permisos WHERE codigo = '{_CODIGO}'"
            )
        )

    _step(engine, "downgrade")

    assert _filas(engine, "SELECT count(*) FROM permisos") == [(0,)]
    assert _filas(engine, "SELECT count(*) FROM usuarios_permisos_override") == [(0,)]
    columnas = _filas(
        engine,
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'tacticals' ORDER BY column_name",
    )
    assert columnas == [("estado",), ("id",)]
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO sell_in_compras (estado) VALUES ('pendiente')"))
    _step(engine, "upgrade")  # and up again


# --- S10: legacy profit offsets wait for approval too ----------------------------------------------------------------


@pytest.mark.postgres
def test_existing_offsets_keep_applying_and_a_new_one_may_wait(engine) -> None:
    _step(engine, "upgrade")
    _step(engine, "upgrade")  # idempotent

    assert _filas(engine, "SELECT monto, estado FROM offsets_ganancia ORDER BY id") == [
        (100, "activa"),
        (-50, "activa"),
    ]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO offsets_ganancia (monto, estado) VALUES (7, 'pendiente')"))
        conn.execute(text("INSERT INTO offsets_ganancia (monto) VALUES (8)"))  # an insert without it applies
    assert _filas(engine, "SELECT estado FROM offsets_ganancia WHERE monto IN (7, 8) ORDER BY monto") == [
        ("pendiente",),
        ("activa",),
    ]
    for valor in ("anulada", None):
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO offsets_ganancia (monto, estado) VALUES (9, :e)"), {"e": valor})


@pytest.mark.postgres
def test_downgrade_refuses_while_an_offset_is_pending_and_drops_the_state_otherwise(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO offsets_ganancia (monto, estado) VALUES (7, 'pendiente')"))

    with pytest.raises(InternalError, match="loads pending approval exist"):
        _step(engine, "downgrade")

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM offsets_ganancia WHERE estado = 'pendiente'"))
    _step(engine, "downgrade")
    columnas = _filas(
        engine,
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'offsets_ganancia' ORDER BY column_name",
    )
    assert columnas == [("id",), ("monto",)]
    assert _filas(engine, "SELECT monto FROM offsets_ganancia ORDER BY id") == [(100,), (-50,)]

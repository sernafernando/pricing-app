"""Migration `20261114_marcas_visibles_excepciones` (marcas-sin-stock S5): creates the exception list table and
seeds `admin.marcas_visibles` for ADMIN. Upgrade, re-run and downgrade on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from tests.services.sell._schema import throwaway_schema

_REVISION = "20261114_marcas_visibles_excepciones"
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_CODIGO = "admin.marcas_visibles"
_STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", "INSERT INTO usuarios VALUES (7)"]
_GRANTED_ROLES = text("""
    SELECT r.codigo FROM roles_permisos_base rp
    JOIN roles r ON r.id = rp.rol_id JOIN permisos p ON p.id = rp.permiso_id
    WHERE p.codigo = :codigo ORDER BY r.codigo
""")


def _step(engine: Engine, step: str) -> None:
    spec = importlib.util.spec_from_file_location("marcas_visibles_excepciones_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _seed_roles(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO roles (id, codigo, nombre, es_sistema, orden, activo)
                VALUES (1, 'ADMIN', 'Admin', true, 1, true), (2, 'PRICING', 'Pricing', false, 4, true)
            """)
        )


@pytest.fixture
def engine() -> Iterator[Engine]:
    tables = [Rol.__table__, Permiso.__table__, RolPermisoBase.__table__, UsuarioPermisoOverride.__table__]
    with throwaway_schema("marcas_visibles_mig", tables, _STUBS, after=_seed_roles) as engine:
        yield engine


def test_upgrade_creates_the_table_and_grants_the_permission_to_admin(engine: Engine) -> None:
    _step(engine, "upgrade")

    with engine.begin() as conn:
        roles = conn.execute(_GRANTED_ROLES, {"codigo": _CODIGO}).scalars().all()
        conn.execute(text("INSERT INTO marcas_visibles_excepciones (marca, creado_por_id) VALUES ('Vieja', 7)"))
        created_at = conn.execute(text("SELECT created_at FROM marcas_visibles_excepciones")).scalar_one()
    assert roles == ["ADMIN"]
    assert created_at is not None
    with pytest.raises(Exception, match="uq_marcas_visibles_excepciones_marca"):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO marcas_visibles_excepciones (marca) VALUES ('Vieja')"))


def test_upgrade_twice_keeps_one_table_permission_and_grant(engine: Engine) -> None:
    _step(engine, "upgrade")
    _step(engine, "upgrade")

    with engine.connect() as conn:
        permisos = conn.execute(text("SELECT COUNT(*) FROM permisos WHERE codigo = :c"), {"c": _CODIGO}).scalar_one()
        roles = conn.execute(_GRANTED_ROLES, {"codigo": _CODIGO}).scalars().all()
    assert permisos == 1
    assert roles == ["ADMIN"]


def test_downgrade_drops_the_table_and_the_permission(engine: Engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido)
                SELECT 7, id, true FROM permisos WHERE codigo = :c
            """),
            {"c": _CODIGO},
        )

    _step(engine, "downgrade")

    with engine.connect() as conn:
        counts = [
            conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override")
        ]
        assert not inspect(conn).has_table("marcas_visibles_excepciones")
    assert counts == [0, 0, 0]


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


class TestMigrationGraph:
    def test_single_head_descends_from_this_revision(self) -> None:
        # Not `get_heads() == [this]`: a later revision must not break this test.
        scripts = _script_directory()
        heads = scripts.get_heads()
        assert len(heads) == 1
        assert _REVISION in {rev.revision for rev in scripts.iterate_revisions(heads[0], "base")}

    def test_chains_on_the_head_of_main(self) -> None:
        assert _script_directory().get_revision(_REVISION).down_revision == "compras_048_auto_vinculo_factura"

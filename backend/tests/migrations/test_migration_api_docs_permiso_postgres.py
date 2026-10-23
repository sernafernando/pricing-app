"""Migration `20261117_api_docs_permiso`: seeds `admin.ver_api_docs` and grants it to ADMIN only, so ADMIN
users can open the in-app API docs right after the deploy. Upgrade, re-run and downgrade on a real Postgres
with the ORM's own permission tables."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text

from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261117_api_docs_permiso.py")
_CODIGO = "admin.ver_api_docs"
_STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", "INSERT INTO usuarios VALUES (7)"]
_GRANTED_ROLES = text("""
    SELECT r.codigo FROM roles_permisos_base rp
    JOIN roles r ON r.id = rp.rol_id JOIN permisos p ON p.id = rp.permiso_id
    WHERE p.codigo = :codigo ORDER BY r.codigo
""")


def _step(engine: Engine, step: str) -> None:
    spec = importlib.util.spec_from_file_location("api_docs_permiso_migration", _PATH)
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
                VALUES (1, 'ADMIN', 'Admin', true, 1, true), (2, 'VENTAS', 'Ventas', true, 2, true)
            """)
        )


@pytest.fixture
def engine() -> Iterator[Engine]:
    tables = [Rol.__table__, Permiso.__table__, RolPermisoBase.__table__, UsuarioPermisoOverride.__table__]
    with throwaway_schema("api_docs_permiso", tables, _STUBS, after=_seed_roles) as engine:
        yield engine


def test_upgrade_creates_the_permission_and_grants_it_to_admin_only(engine: Engine) -> None:
    _step(engine, "upgrade")

    with engine.connect() as conn:
        categoria = conn.execute(text("SELECT categoria FROM permisos WHERE codigo = :c"), {"c": _CODIGO}).scalar_one()
        roles = conn.execute(_GRANTED_ROLES, {"codigo": _CODIGO}).scalars().all()

    assert categoria == "administracion"
    assert roles == ["ADMIN"]


def test_upgrade_twice_keeps_a_single_permission_and_grant(engine: Engine) -> None:
    _step(engine, "upgrade")
    _step(engine, "upgrade")

    with engine.connect() as conn:
        permisos = conn.execute(text("SELECT COUNT(*) FROM permisos WHERE codigo = :c"), {"c": _CODIGO}).scalar_one()
        roles = conn.execute(_GRANTED_ROLES, {"codigo": _CODIGO}).scalars().all()

    assert permisos == 1
    assert roles == ["ADMIN"]


def test_downgrade_removes_grants_overrides_and_the_permission(engine: Engine) -> None:
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
    assert counts == [0, 0, 0]

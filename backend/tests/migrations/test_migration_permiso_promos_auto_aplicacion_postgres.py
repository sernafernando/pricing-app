"""Migration `20261117_permiso_promos_auto_aplicacion`: seeds `promos.auto_aplicacion` with no role grants."""

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
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261117_permiso_promos_auto_aplicacion.py")
_CODIGO = "promos.auto_aplicacion"
_STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", "INSERT INTO usuarios VALUES (7)"]
_GRANTED_ROLES = text(
    """
    SELECT r.codigo FROM roles_permisos_base rp
    JOIN roles r ON r.id = rp.rol_id JOIN permisos p ON p.id = rp.permiso_id
    WHERE p.codigo = :codigo ORDER BY r.codigo
    """
)


def _step(engine: Engine, step: str) -> None:
    spec = importlib.util.spec_from_file_location("permiso_promos_auto_aplicacion_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _seed_roles(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO roles (id, codigo, nombre, es_sistema, orden, activo)
                VALUES
                    (1, 'ADMIN', 'Admin', true, 1, true),
                    (2, 'PRICING', 'Pricing', true, 2, true),
                    (3, 'GERENTE', 'Gerente', true, 3, true)
                """
            )
        )


@pytest.fixture
def engine() -> Iterator[Engine]:
    tables = [Rol.__table__, Permiso.__table__, RolPermisoBase.__table__, UsuarioPermisoOverride.__table__]
    with throwaway_schema("permiso_promos_auto", tables, _STUBS, after=_seed_roles) as engine:
        yield engine


def test_upgrade_creates_permission_with_no_role_grants(engine: Engine) -> None:
    _step(engine, "upgrade")

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT categoria, es_critico FROM permisos WHERE codigo = :c"),
            {"c": _CODIGO},
        ).one()
        roles = conn.execute(_GRANTED_ROLES, {"codigo": _CODIGO}).scalars().all()

    assert row.categoria == "promos"
    assert row.es_critico is True
    assert roles == []


def test_upgrade_twice_keeps_a_single_permission(engine: Engine) -> None:
    _step(engine, "upgrade")
    _step(engine, "upgrade")

    with engine.connect() as conn:
        permisos = conn.execute(
            text("SELECT COUNT(*) FROM permisos WHERE codigo = :c"),
            {"c": _CODIGO},
        ).scalar_one()
        roles = conn.execute(_GRANTED_ROLES, {"codigo": _CODIGO}).scalars().all()

    assert permisos == 1
    assert roles == []


def test_downgrade_removes_permission(engine: Engine) -> None:
    _step(engine, "upgrade")
    _step(engine, "downgrade")

    with engine.connect() as conn:
        permisos = conn.execute(
            text("SELECT COUNT(*) FROM permisos WHERE codigo = :c"),
            {"c": _CODIGO},
        ).scalar_one()

    assert permisos == 0

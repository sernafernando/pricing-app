"""ODD `metricas-ml-scope-pm` T3: PRICING and VENTAS (the roles that open the old
ML dashboard) get `ml_metricas.ver` and `ml_metricas.ver_ganancia`, in a migration
that is idempotent and whose downgrade removes only those two role grants."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.routers import ml_metricas

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261006_ml_metricas_permisos_pm"
_BASE = "20261001_ml_metricas_permisos"
CODES = {ml_metricas.PERMISO_VER, ml_metricas.PERMISO_GANANCIA}


def _script() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _module():
    return _script().get_revision(_REVISION).module


def test_the_revision_is_the_single_head() -> None:
    script = _script()
    assert script.get_heads() == [_REVISION]


def test_it_grants_exactly_the_board_permissions_to_pricing_and_ventas() -> None:
    module = _module()
    assert set(module.ROL_PERMISOS) == {"PRICING", "VENTAS"}
    for codes in module.ROL_PERMISOS.values():
        assert set(codes) == CODES


@pytest.fixture()
def catalog():
    """Roles, the two permissions (seeded by the base migration) and one
    unrelated permission, on an in-memory database with the real unique key."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE roles (id INTEGER PRIMARY KEY, codigo TEXT)"))
        conn.execute(sa.text("CREATE TABLE permisos (id INTEGER PRIMARY KEY, codigo TEXT UNIQUE)"))
        conn.execute(
            sa.text(
                "CREATE TABLE roles_permisos_base (rol_id INTEGER, permiso_id INTEGER, PRIMARY KEY (rol_id, permiso_id))"
            )
        )
        for n, codigo in enumerate(("ADMIN", "PRICING", "VENTAS", "COMPRAS"), start=1):
            conn.execute(sa.text("INSERT INTO roles VALUES (:id, :c)"), {"id": n, "c": codigo})
        for n, codigo in enumerate((*sorted(CODES), "otro.permiso"), start=1):
            conn.execute(sa.text("INSERT INTO permisos VALUES (:id, :c)"), {"id": n, "c": codigo})
        # ADMIN already holds both (base migration); VENTAS holds an unrelated one.
        conn.execute(sa.text("INSERT INTO roles_permisos_base VALUES (1, 1), (1, 2), (3, 3)"))
    yield engine
    engine.dispose()


def _grants(engine) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT r.codigo, p.codigo FROM roles_permisos_base rp "
                "JOIN roles r ON r.id = rp.rol_id JOIN permisos p ON p.id = rp.permiso_id"
            )
        )
        return {(rol, permiso) for rol, permiso in rows}


def _run(engine, step: str) -> None:
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(_module(), step)()


def test_upgrade_grants_both_permissions_and_is_idempotent(catalog) -> None:
    before = _grants(catalog)

    _run(catalog, "upgrade")
    _run(catalog, "upgrade")

    added = _grants(catalog) - before
    assert added == {(rol, code) for rol in ("PRICING", "VENTAS") for code in CODES}
    assert ("ADMIN", ml_metricas.PERMISO_VER) in _grants(catalog)


def test_downgrade_removes_only_those_grants_and_keeps_the_permissions(catalog) -> None:
    before = _grants(catalog)
    _run(catalog, "upgrade")

    _run(catalog, "downgrade")

    assert _grants(catalog) == before  # ADMIN's grants and VENTAS's other permission survive
    with catalog.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM permisos")).scalar() == 3

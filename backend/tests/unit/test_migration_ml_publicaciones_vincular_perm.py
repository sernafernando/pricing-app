"""P5L2.T1: the `ml_publicaciones.vincular` permission ships in its own migration on the single
alembic line, is granted to ADMIN, and downgrades cleanly. The upgrade/downgrade run for real on a
throwaway Postgres schema holding the real permission tables."""

from __future__ import annotations

import os
import uuid

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261007_ml_publicaciones_vincular_perm"
CODIGO = "ml_publicaciones.vincular"


def _script() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_single_head_and_it_is_this_revision() -> None:
    script = _script()
    assert script.get_heads() == [_REVISION]


def test_declares_the_catalog_row_like_the_other_ml_ops_permissions() -> None:
    module = _script().get_revision(_REVISION).module
    assert module.CODIGO == CODIGO
    assert module.PERMISO_CATEGORIA == "ml_ops"
    assert module.PERMISO_ES_CRITICO is False
    assert module.ROL_PERMISOS == {"ADMIN": [CODIGO]}
    assert module.PERMISO_ORDEN == 205  # 200-204 are taken by the other ml_ops permissions


@pytest.fixture()
def pg_schema():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"perm_t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _run(eng, migration, direction: str) -> None:
    with eng.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(migration, direction)()


def test_upgrade_grants_admin_only_and_is_idempotent_and_downgrade_removes_everything(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE roles (id serial PRIMARY KEY, codigo varchar(50) UNIQUE NOT NULL)"))
        conn.execute(
            text(
                "CREATE TABLE permisos (id serial PRIMARY KEY, codigo varchar(100) UNIQUE NOT NULL, "
                "nombre varchar(255) NOT NULL, descripcion text, categoria varchar(50) NOT NULL, "
                "orden integer, es_critico boolean, created_at timestamptz DEFAULT now())"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE roles_permisos_base (id serial PRIMARY KEY, rol_id integer NOT NULL, "
                "permiso_id integer NOT NULL, UNIQUE (rol_id, permiso_id))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE usuarios_permisos_override (id serial PRIMARY KEY, usuario_id integer NOT NULL, "
                "permiso_id integer NOT NULL)"
            )
        )
        conn.execute(text("INSERT INTO roles (codigo) VALUES ('ADMIN'), ('GERENTE'), ('VENTAS')"))

    _run(eng, module, "upgrade")
    _run(eng, module, "upgrade")  # ON CONFLICT DO NOTHING: re-running changes nothing

    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT categoria, orden, es_critico FROM permisos WHERE codigo = :c"), {"c": CODIGO}
        ).one()
        assert tuple(row) == ("ml_ops", 205, False)
        granted = conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c"
            ),
            {"c": CODIGO},
        ).all()
    assert [r[0] for r in granted] == ["ADMIN"]

    with eng.begin() as conn:
        pid = conn.execute(text("SELECT id FROM permisos WHERE codigo = :c"), {"c": CODIGO}).scalar_one()
        conn.execute(text("INSERT INTO usuarios_permisos_override (usuario_id, permiso_id) VALUES (7, :p)"), {"p": pid})

    _run(eng, module, "downgrade")
    with eng.connect() as conn:
        for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table

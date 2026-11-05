"""Gestión Full gets its own `gestion_full.ver` permission (owner 2026-11-05) instead of depending on Productos /
Ventas ML. The migration grants it to every role and per-user grant that opens the screen today, so nobody loses
access, and downgrades cleanly. The upgrade/downgrade run for real on a throwaway Postgres schema."""

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
_REVISION = "20261106_gestion_full_ver"
CODIGO = "gestion_full.ver"


def _script() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261105_merge_grupos_ver_ml_ads_soft_delete"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


@pytest.fixture()
def pg_schema():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"gfver_{uuid.uuid4().hex[:8]}"
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


def _tables(conn) -> None:
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
            "permiso_id integer NOT NULL, concedido boolean NOT NULL, otorgado_por_id integer, motivo text, "
            "created_at timestamptz DEFAULT now(), UNIQUE (usuario_id, permiso_id))"
        )
    )


def _grant_role(conn, rol: str, codigo: str) -> None:
    conn.execute(
        text(
            "INSERT INTO roles_permisos_base (rol_id, permiso_id) SELECT r.id, p.id FROM roles r, permisos p "
            "WHERE r.codigo = :r AND p.codigo = :c"
        ),
        {"r": rol, "c": codigo},
    )


def _override(conn, usuario_id: int, codigo: str, concedido: bool) -> None:
    conn.execute(
        text(
            "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) "
            "SELECT :u, id, :g FROM permisos WHERE codigo = :c"
        ),
        {"u": usuario_id, "c": codigo, "g": concedido},
    )


def _holders(conn):
    roles = (
        conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c ORDER BY r.codigo"
            ),
            {"c": CODIGO},
        )
        .scalars()
        .all()
    )
    users = (
        conn.execute(
            text(
                "SELECT o.usuario_id FROM usuarios_permisos_override o JOIN permisos p ON p.id = o.permiso_id "
                "WHERE p.codigo = :c AND o.concedido ORDER BY o.usuario_id"
            ),
            {"c": CODIGO},
        )
        .scalars()
        .all()
    )
    return roles, users


def test_whoever_opens_the_screen_today_keeps_it_and_downgrade_removes_everything(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        _tables(conn)
        conn.execute(text("INSERT INTO roles (codigo) VALUES ('ADMIN'), ('PRICING'), ('VENTAS'), ('DEPOSITO')"))
        conn.execute(
            text(
                "INSERT INTO permisos (codigo, nombre, categoria) VALUES "
                "('productos.ver', 'p', 'productos'), ('ml_ops.ver', 'm', 'ventas'), ('rma.ver', 'r', 'soporte')"
            )
        )
        _grant_role(conn, "PRICING", "productos.ver")
        _grant_role(conn, "VENTAS", "ml_ops.ver")
        _grant_role(conn, "DEPOSITO", "rma.ver")
        _override(conn, 7, "productos.ver", True)  # a per-user grant opens the screen today
        _override(conn, 8, "ml_ops.ver", False)  # a revoke does not
        _override(conn, 9, "rma.ver", True)

    _run(eng, module, "upgrade")
    _run(eng, module, "upgrade")  # ON CONFLICT DO NOTHING: re-running changes nothing

    with eng.connect() as conn:
        row = conn.execute(text("SELECT categoria, es_critico FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert tuple(row) == ("productos", False)
        assert _holders(conn) == (["ADMIN", "PRICING", "VENTAS"], [7])

    _run(eng, module, "downgrade")
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM permisos WHERE codigo = :c"), {"c": CODIGO}).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM roles_permisos_base")).scalar_one() == 3
        assert conn.execute(text("SELECT count(*) FROM usuarios_permisos_override")).scalar_one() == 3

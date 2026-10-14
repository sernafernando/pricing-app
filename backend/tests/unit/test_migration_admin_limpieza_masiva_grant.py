"""The bulk "limpiar rebate / web transferencia" endpoints move from the view
permission `admin.ver_panel` to the existing catalog code `admin.limpieza_masiva`
(seeded by create_permisos_system for exactly this action, but never enforced).
The migration must make sure the row exists and grant it to every role, and every
user override, that holds `admin.ver_panel`, so nobody who can run the cleanup
today loses it. Upgrade runs for real on a throwaway Postgres schema."""

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
_REVISION = "20261019_admin_limpieza_masiva_grant"
CODIGO = "admin.limpieza_masiva"


def _script() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261018_merge_sale_lines_promo_refresh"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


@pytest.fixture()
def pg_schema():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"limp_t_{uuid.uuid4().hex[:8]}"
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


def _upgrade(eng) -> None:
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()


def _create_tables(conn) -> None:
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


def _roles_with(conn, codigo: str) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
            "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c ORDER BY r.codigo"
        ),
        {"c": codigo},
    ).all()
    return [r[0] for r in rows]


def _overrides_for(conn, codigo: str) -> dict[int, bool]:
    rows = conn.execute(
        text(
            "SELECT o.usuario_id, o.concedido FROM usuarios_permisos_override o "
            "JOIN permisos p ON p.id = o.permiso_id WHERE p.codigo = :c"
        ),
        {"c": codigo},
    ).all()
    return {r[0]: r[1] for r in rows}


def test_upgrade_grants_limpieza_masiva_to_every_ver_panel_holder(pg_schema) -> None:
    eng = pg_schema
    with eng.begin() as conn:
        _create_tables(conn)
        conn.execute(text("INSERT INTO roles (codigo) VALUES ('ADMIN'), ('GERENTE'), ('PRICING'), ('VENTAS')"))
        conn.execute(
            text(
                "INSERT INTO permisos (codigo, nombre, categoria) VALUES "
                "('admin.ver_panel', 'Ver panel', 'administracion')"
            )
        )
        # ADMIN and GERENTE see the panel; PRICING and VENTAS do not.
        conn.execute(
            text(
                "INSERT INTO roles_permisos_base (rol_id, permiso_id) "
                "SELECT r.id, p.id FROM roles r, permisos p "
                "WHERE r.codigo IN ('ADMIN', 'GERENTE') AND p.codigo = 'admin.ver_panel'"
            )
        )
        # User 7 is granted ver_panel by override; user 8 is denied it.
        conn.execute(
            text(
                "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) "
                "SELECT u, p.id, c FROM permisos p, (VALUES (7, true), (8, false)) AS v(u, c) "
                "WHERE p.codigo = 'admin.ver_panel'"
            )
        )

    _upgrade(eng)
    _upgrade(eng)  # idempotent

    with eng.connect() as conn:
        row = conn.execute(text("SELECT categoria, es_critico FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert tuple(row) == ("administracion", True)
        assert _roles_with(conn, CODIGO) == ["ADMIN", "GERENTE"]
        assert _overrides_for(conn, CODIGO) == {7: True}


def test_upgrade_keeps_an_existing_row_and_an_explicit_denial(pg_schema) -> None:
    eng = pg_schema
    with eng.begin() as conn:
        _create_tables(conn)
        conn.execute(text("INSERT INTO roles (codigo) VALUES ('ADMIN')"))
        conn.execute(
            text(
                "INSERT INTO permisos (codigo, nombre, categoria, orden, es_critico) VALUES "
                "('admin.ver_panel', 'Ver panel', 'administracion', 50, false), "
                "('admin.limpieza_masiva', 'Limpieza masiva de datos', 'administracion', 55, true)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) "
                "SELECT 9, p.id, CASE WHEN p.codigo = 'admin.ver_panel' THEN true ELSE false END "
                "FROM permisos p"
            )
        )

    _upgrade(eng)

    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM permisos WHERE codigo = :c"), {"c": CODIGO}).scalar_one() == 1
        # User 9 was explicitly denied the cleanup: the migration must not flip it.
        assert _overrides_for(conn, CODIGO) == {9: False}

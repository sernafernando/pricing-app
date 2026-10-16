"""Migration `20261026_tplink_tema_permiso`, executed against Postgres.

Runs the real upgrade()/downgrade() inside a throwaway schema of the Postgres
test DB that holds minimal copies of the three tables the migration touches.
The grant/override foreign keys deliberately have NO `ON DELETE CASCADE`, so a
downgrade only passes if it deletes the grants and overrides itself.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261026_tplink_tema_permiso.py"

SCHEMA_DDL = [
    """
    CREATE TABLE permisos (
        id SERIAL PRIMARY KEY,
        codigo VARCHAR(100) NOT NULL UNIQUE,
        nombre VARCHAR(255) NOT NULL,
        descripcion TEXT,
        categoria VARCHAR(50) NOT NULL,
        orden INTEGER,
        es_critico BOOLEAN,
        created_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE roles_permisos_base (
        id SERIAL PRIMARY KEY,
        rol_id INTEGER NOT NULL,
        permiso_id INTEGER NOT NULL REFERENCES permisos(id)
    )
    """,
    """
    CREATE TABLE usuarios_permisos_override (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL,
        permiso_id INTEGER NOT NULL REFERENCES permisos(id),
        concedido BOOLEAN NOT NULL
    )
    """,
]


def _load_migration():
    spec = importlib.util.spec_from_file_location("tplink_tema_permiso_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"tplink_tema_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        for ddl in SCHEMA_DDL:
            conn.execute(text(ddl))
        # A neighbour permission with its own grants: the migration must not touch it.
        conn.execute(
            text(
                "INSERT INTO permisos (codigo, nombre, categoria, orden, es_critico) "
                "VALUES ('dashboard_tplink.ver', 'Ver dashboard TP-Link', 'ventas_ml', 60, false)"
            )
        )
        conn.execute(text("INSERT INTO roles_permisos_base (rol_id, permiso_id) SELECT 1, id FROM permisos"))
        conn.execute(
            text(
                "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) SELECT 9, id, true FROM permisos"
            )
        )
    try:
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def _run(engine, step: str) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(migration, step)()


def _scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def _tema_row(engine):
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT codigo, nombre, descripcion, categoria, orden, es_critico, created_at IS NOT NULL "
                    "FROM permisos WHERE codigo = 'tplink.tema'"
                )
            )
            .mappings()
            .all()
        )


@pytest.mark.postgres
class TestTplinkTemaPermisoMigration:
    def test_upgrade_inserts_the_permission(self, engine) -> None:
        _run(engine, "upgrade")
        rows = _tema_row(engine)
        assert [dict(r) for r in rows] == [
            {
                "codigo": "tplink.tema",
                "nombre": "Ver tema TP-Link",
                "descripcion": "Aplica los colores y el logo de TP-Link en toda la interfaz",
                "categoria": "ventas_ml",
                "orden": 63,
                "es_critico": False,
                "?column?": True,
            }
        ]

    def test_upgrade_grants_it_to_no_role_and_no_user(self, engine) -> None:
        _run(engine, "upgrade")
        grants = _scalar(
            engine,
            "SELECT count(*) FROM roles_permisos_base r JOIN permisos p ON p.id = r.permiso_id "
            "WHERE p.codigo = 'tplink.tema'",
        )
        overrides = _scalar(
            engine,
            "SELECT count(*) FROM usuarios_permisos_override o JOIN permisos p ON p.id = o.permiso_id "
            "WHERE p.codigo = 'tplink.tema'",
        )
        assert (grants, overrides) == (0, 0)

    def test_upgrade_is_idempotent(self, engine) -> None:
        _run(engine, "upgrade")
        _run(engine, "upgrade")
        assert _scalar(engine, "SELECT count(*) FROM permisos WHERE codigo = 'tplink.tema'") == 1

    def test_downgrade_removes_grants_overrides_and_the_permission(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO roles_permisos_base (rol_id, permiso_id) SELECT 2, id FROM permisos WHERE codigo = 'tplink.tema'"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) "
                    "SELECT 1, id, true FROM permisos WHERE codigo = 'tplink.tema'"
                )
            )

        _run(engine, "downgrade")

        assert _tema_row(engine) == []
        assert _scalar(engine, "SELECT count(*) FROM roles_permisos_base") == 1
        assert _scalar(engine, "SELECT count(*) FROM usuarios_permisos_override") == 1

    def test_downgrade_leaves_other_permissions_alone(self, engine) -> None:
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        assert _scalar(engine, "SELECT codigo FROM permisos") == "dashboard_tplink.ver"
        assert _scalar(engine, "SELECT count(*) FROM roles_permisos_base") == 1
        assert _scalar(engine, "SELECT count(*) FROM usuarios_permisos_override") == 1

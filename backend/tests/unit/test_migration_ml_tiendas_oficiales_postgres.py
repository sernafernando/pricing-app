"""Migration `20261006_ml_tiendas_oficiales`: creates the table, seeds the four
stores that used to be hardcoded, seeds the `admin.tiendas_oficiales`
permission for ADMIN, is idempotent, and downgrade removes all of it.

Runs inside a throwaway schema of the Postgres test DB (with minimal
`roles` / `permisos` / `roles_permisos_base` stand-ins) so nothing leaks into
the shared tables.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261006_ml_tiendas_oficiales.py"

_SEED = {57997: "Gauss", 2645: "TP-Link", 471846: "TP-Link", 144: "Forza/Verbatim", 191942: "Multi-marca"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("ml_tiendas_oficiales_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"tiendas_mig_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE roles (id SERIAL PRIMARY KEY, codigo VARCHAR(50) UNIQUE NOT NULL)"))
        conn.execute(
            text(
                """
                CREATE TABLE permisos (
                    id SERIAL PRIMARY KEY, codigo VARCHAR(100) UNIQUE NOT NULL, nombre VARCHAR(255) NOT NULL,
                    descripcion TEXT, categoria VARCHAR(50) NOT NULL, orden INTEGER NOT NULL DEFAULT 0,
                    es_critico BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE TABLE roles_permisos_base (rol_id INTEGER NOT NULL, permiso_id INTEGER NOT NULL,"
                " PRIMARY KEY (rol_id, permiso_id))"
            )
        )
        conn.execute(text("CREATE TABLE usuarios_permisos_override (permiso_id INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO roles (codigo) VALUES ('ADMIN'), ('GERENTE')"))
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


def _stores(engine) -> dict[int, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT store_id, nombre FROM ml_tiendas_oficiales")).all()
    return {r[0]: r[1] for r in rows}


@pytest.mark.postgres
class TestMlTiendasOficialesMigration:
    def test_upgrade_creates_the_table_seeded_with_the_hardcoded_stores_plus_the_new_tplink_id(self, engine) -> None:
        _run(engine, "upgrade")

        assert _stores(engine) == _SEED
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT store_id, orden, activa FROM ml_tiendas_oficiales ORDER BY orden")).all()
        # Display order of the old `TIENDAS_OFICIALES_ORDER`, all active.
        assert [r[0] for r in rows] == [57997, 2645, 471846, 144, 191942]
        assert all(r[2] is True for r in rows)

    def test_both_tplink_ids_share_the_clave_and_clave_is_not_unique(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            claves = {r[0]: r[1] for r in conn.execute(text("SELECT store_id, clave FROM ml_tiendas_oficiales")).all()}
            assert claves == {57997: None, 2645: "tplink", 471846: "tplink", 144: None, 191942: None}
            # The old and the new id of one store share a clave.
            conn.execute(
                text("INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave) VALUES (9, 'TP-Link', 'tplink')")
            )

    def test_store_id_is_the_primary_key(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            with pytest.raises(Exception):
                conn.execute(text("INSERT INTO ml_tiendas_oficiales (store_id, nombre) VALUES (57997, 'dup')"))

    def test_upgrade_grants_the_permission_to_admin_only(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            granted = conn.execute(
                text(
                    "SELECT r.codigo FROM roles_permisos_base rp JOIN roles r ON r.id = rp.rol_id "
                    "JOIN permisos p ON p.id = rp.permiso_id WHERE p.codigo = 'admin.tiendas_oficiales'"
                )
            ).all()
        assert [g[0] for g in granted] == ["ADMIN"]

    def test_upgrade_is_idempotent_and_keeps_admin_edits(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(text("UPDATE ml_tiendas_oficiales SET nombre = 'Renamed' WHERE store_id = 57997"))
        _run(engine, "upgrade")  # second run: no error, admin edit untouched
        assert _stores(engine) == {**_SEED, 57997: "Renamed"}

    def test_downgrade_removes_table_and_permission(self, engine) -> None:
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('ml_tiendas_oficiales')")).scalar() is None
            assert (
                conn.execute(text("SELECT count(*) FROM permisos WHERE codigo = 'admin.tiendas_oficiales'")).scalar()
                == 0
            )

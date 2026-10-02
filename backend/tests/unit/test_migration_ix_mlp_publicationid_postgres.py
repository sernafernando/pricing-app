"""Review finding: `CREATE INDEX CONCURRENTLY IF NOT EXISTS` keeps an INVALID
index left behind by an interrupted earlier build (Postgres leaves the name
taken by an index it never finished and never uses). The migration must
notice (`pg_index.indisvalid`), drop it and build it again."""

from __future__ import annotations

import os
from pathlib import Path
import importlib.util

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261001_ix_mlp_publicationid.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("ix_mlp_publicationid_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def autocommit_conn():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(os.environ.get("POSTGRES_TEST_URL", POSTGRES_TEST_URL), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        created = not sa_inspect(conn).has_table("tb_mercadolibre_items_publicados")
        if created:
            conn.execute(
                text(
                    "CREATE TABLE tb_mercadolibre_items_publicados (mlp_id INTEGER PRIMARY KEY, mlp_publicationid VARCHAR(50))"
                )
            )
        yield conn
        if created:
            conn.execute(text("DROP TABLE tb_mercadolibre_items_publicados"))
    engine.dispose()


def _validity(conn, name: str):
    return conn.execute(
        text(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name AND pg_table_is_visible(c.oid)"
        ),
        {"name": name},
    ).scalar()


def _run_upgrade(conn) -> None:
    """The migration the way `alembic upgrade` runs it: a transactional
    connection whose `autocommit_block` steps out for CONCURRENTLY."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _load_migration()
    engine = create_engine(str(conn.engine.url.render_as_string(hide_password=False)))
    try:
        with engine.connect() as migration_conn:
            ctx = MigrationContext.configure(migration_conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                migration.upgrade()
    finally:
        engine.dispose()


@pytest.mark.postgres
class TestPublicationIdIndexMigration:
    def test_creates_the_index_when_missing(self, autocommit_conn) -> None:
        name = _load_migration().INDEX
        autocommit_conn.execute(text(f"DROP INDEX IF EXISTS {name}"))

        _run_upgrade(autocommit_conn)

        assert _validity(autocommit_conn, name) is True

    def test_rebuilds_an_invalid_index_left_by_an_interrupted_build(self, autocommit_conn) -> None:
        name = _load_migration().INDEX
        autocommit_conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        autocommit_conn.execute(text(f"CREATE INDEX {name} ON tb_mercadolibre_items_publicados (mlp_publicationid)"))
        # What an interrupted CREATE INDEX CONCURRENTLY leaves behind.
        autocommit_conn.execute(text(f"UPDATE pg_index SET indisvalid = false WHERE indexrelid = '{name}'::regclass"))
        assert _validity(autocommit_conn, name) is False

        _run_upgrade(autocommit_conn)

        assert _validity(autocommit_conn, name) is True

    def test_a_valid_index_is_left_alone(self, autocommit_conn) -> None:
        name = _load_migration().INDEX
        autocommit_conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        autocommit_conn.execute(text(f"CREATE INDEX {name} ON tb_mercadolibre_items_publicados (mlp_publicationid)"))
        oid_before = autocommit_conn.execute(text(f"SELECT '{name}'::regclass::oid")).scalar()

        _run_upgrade(autocommit_conn)

        assert autocommit_conn.execute(text(f"SELECT '{name}'::regclass::oid")).scalar() == oid_before

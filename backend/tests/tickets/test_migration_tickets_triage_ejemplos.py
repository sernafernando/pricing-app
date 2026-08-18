"""Tests for the `20260814_tickets_triage_ejemplos` migration
(tickets-triage-feedback PR3): creates `tickets_triage_ejemplos` (pgvector
corpus for best-effort correction capture).

Two layers, mirroring `test_migration_propuesta_corregida.py` /
`test_migration_triage_auto_apply_backfill.py`:
1. Dialect-agnostic revision-graph check (runs everywhere, including SQLite
   CI): single-head chain, correctly linked.
2. `@pytest.mark.postgres`: runs the migration's REAL `upgrade()` (via
   Alembic's `Operations` proxy, same pattern as
   `test_migration_propuesta_corregida.py::_run_migration_fn`) against a
   live Postgres connection, in its own throwaway schema with minimal stub
   `tickets`/`tickets_propuestas_ia` FK-target tables, and asserts the
   table, the `ix_tickets_triage_ejemplos_campo_active` index, and the HNSW
   index all exist, plus that the `propuesta_id` unique constraint rejects
   a double insert for the same `propuesta_id`.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_migration_tickets_triage_ejemplos.py -v
    pytest tests/tickets/test_migration_tickets_triage_ejemplos.py -v -m postgres
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REVISION = "20260814_tickets_triage_ejemplos"
_DOWN_REVISION = "20260813_propuesta_corregida"

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL", "postgresql+psycopg2://postgres@localhost:5432/pricing_test")


def _postgres_reachable() -> bool:
    try:
        probe = sa.create_engine(POSTGRES_TEST_URL)
        with probe.connect():
            pass
        probe.dispose()
        return True
    except Exception:
        return False


def _script_directory() -> ScriptDirectory:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = _BACKEND_ROOT / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("tickets_triage_ejemplos_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration_fn(conn, fn) -> None:
    """Runs a migration's `upgrade` (which calls `op.get_bind()` internally)
    against `conn`'s own connection/transaction — mirrors
    `test_migration_propuesta_corregida.py`'s helper."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    ctx = MigrationContext.configure(conn)
    op_obj = Operations(ctx)
    op_obj._install_proxy()
    try:
        fn()
    finally:
        op_obj._remove_proxy()


class TestMigrationGraph:
    """Dialect-agnostic — runs on SQLite CI too."""

    def test_revision_is_registered_and_linked(self) -> None:
        script_dir = _script_directory()
        revision = script_dir.get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == _DOWN_REVISION

    def test_revision_is_reachable_from_head_single_head_chain(self) -> None:
        script_dir = _script_directory()
        heads = script_dir.get_heads()
        assert len(heads) == 1
        ancestors = {rev.revision for rev in script_dir.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in ancestors


@pytest.fixture()
def pg_upgraded_conn():
    """A raw Postgres connection, isolated in its own throwaway schema, with
    minimal stub `tickets`/`tickets_propuestas_ia` FK-target tables (id-only
    — this migration's own upgrade() only needs the referenced tables to
    exist, not their full real shape) followed by the migration's real
    `upgrade()`."""
    if not _postgres_reachable():
        pytest.skip(
            f"PostgreSQL not reachable at {POSTGRES_TEST_URL} — set POSTGRES_TEST_URL "
            "or start a local PostgreSQL to run @pytest.mark.postgres tests."
        )
    engine = sa.create_engine(POSTGRES_TEST_URL)
    schema = f"migr_ejemplos_{uuid.uuid4().hex[:8]}"
    conn = engine.connect()
    conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    conn.execute(sa.text(f'SET search_path TO "{schema}"'))
    conn.execute(sa.text("CREATE TABLE tickets (id SERIAL PRIMARY KEY)"))
    conn.execute(sa.text("CREATE TABLE tickets_propuestas_ia (id SERIAL PRIMARY KEY)"))
    conn.execute(sa.text("INSERT INTO tickets (id) VALUES (1)"))
    conn.execute(sa.text("INSERT INTO tickets_propuestas_ia (id) VALUES (1)"))
    conn.commit()

    migration = _load_migration()
    _run_migration_fn(conn, migration.upgrade)
    conn.commit()

    try:
        yield conn
    finally:
        conn.rollback()
        conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        conn.commit()
        conn.close()
        engine.dispose()


@pytest.mark.postgres
class TestUpgradeCreatesTableAndIndexes:
    def test_table_and_indexes_exist(self, pg_upgraded_conn) -> None:
        conn = pg_upgraded_conn
        inspector = sa.inspect(conn)
        assert inspector.has_table("tickets_triage_ejemplos")

        index_names = {ix["name"] for ix in inspector.get_indexes("tickets_triage_ejemplos")}
        assert "ix_tickets_triage_ejemplos_campo_active" in index_names

        hnsw_exists = conn.execute(
            sa.text(
                "SELECT 1 FROM pg_indexes WHERE tablename = 'tickets_triage_ejemplos' "
                "AND indexname = 'idx_tickets_triage_ejemplos_embedding_hnsw'"
            )
        ).first()
        assert hnsw_exists is not None

    def test_propuesta_id_unique_constraint_rejects_double_insert(self, pg_upgraded_conn) -> None:
        conn = pg_upgraded_conn
        conn.execute(
            sa.text(
                "INSERT INTO tickets_triage_ejemplos "
                "(ticket_id, propuesta_id, campo, texto, valor_ia, valor_corregido, embedding) "
                "VALUES (1, 1, 'severidad', 'texto', 'mayor', 'menor', :emb)"
            ),
            {"emb": "[" + ",".join(["0.1"] * 384) + "]"},
        )
        conn.commit()

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO tickets_triage_ejemplos "
                    "(ticket_id, propuesta_id, campo, texto, valor_ia, valor_corregido, embedding) "
                    "VALUES (1, 1, 'urgencia', 'otro texto', 'baja', 'alta', :emb)"
                ),
                {"emb": "[" + ",".join(["0.2"] * 384) + "]"},
            )
        conn.rollback()

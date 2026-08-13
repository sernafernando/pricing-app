"""Tests for the `20260813_propuesta_corregida` migration
(tickets-triage-feedback PR1): widens `tickets_propuestas_ia.estado`'s CHECK
to admit `'corregida'`, adds `valor_corregido`, and — the part that must be
proven with real DATA, not by exit code — the deliberately lossy `downgrade()`
remap of `corregida` rows to `descartada`.

Two layers, mirroring `test_migration_ml_bot_messages_bot_columns.py`:
1. Dialect-agnostic revision-graph check (runs everywhere, including SQLite
   CI): single-head chain, correctly linked.
2. `@pytest.mark.postgres`: runs the migration's REAL `upgrade()`/
   `downgrade()` against a live Postgres connection, on a table built from
   raw DDL matching the PRE-migration shape (4-value CHECK, no
   `valor_corregido`) — not the ORM model, which already carries the
   post-migration schema once this PR's model change lands, so building
   from the model would make the migration's own ADD COLUMN/CHECK-widen
   DDL untestable. Verifies by RE-QUERYING the row in both directions
   (post-upgrade insert, post-downgrade re-read), never by exit code.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_migration_propuesta_corregida.py -v
    pytest tests/tickets/test_migration_propuesta_corregida.py -v -m postgres
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
_REVISION = "20260813_propuesta_corregida"
_DOWN_REVISION = "20260812_triage_auto_apply"

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
    spec = importlib.util.spec_from_file_location("propuesta_corregida_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
def pg_pre_migration_conn():
    """A raw Postgres connection with `tickets_propuestas_ia` built from
    SQL matching the state JUST BEFORE this migration: `estado` CHECK with
    only the 4 old values, no `valor_corregido` column. Deliberately NOT
    the ORM model (`PropuestaIA.__table__`/`pg_tickets_db`) — after this
    PR's model change, that table already carries the post-migration
    schema, which would make the migration's own ADD COLUMN/CHECK-widen
    DDL untestable.

    Isolated in its OWN throwaway schema (not `public`): `pg_tickets_engine`
    (session-scoped, used by `test_confirmacion_service.py`/
    `test_propuesta_ia_model.py`/etc.) creates a REAL `tickets_propuestas_ia`
    table in the same physical `pricing_test` database and keeps it alive
    for the whole test session — an unqualified `CREATE TABLE` here would
    collide with it whenever this file runs after one of those (real
    failure caught running the full suite, not just this file in
    isolation)."""
    if not _postgres_reachable():
        pytest.skip(
            f"PostgreSQL not reachable at {POSTGRES_TEST_URL} — set POSTGRES_TEST_URL "
            "or start a local PostgreSQL to run @pytest.mark.postgres tests."
        )
    engine = sa.create_engine(POSTGRES_TEST_URL)
    schema = f"migr_corregida_{uuid.uuid4().hex[:8]}"
    conn = engine.connect()
    conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    conn.execute(sa.text(f'SET search_path TO "{schema}"'))
    conn.execute(
        sa.text(
            """
            CREATE TABLE tickets_propuestas_ia (
                id SERIAL PRIMARY KEY,
                campo VARCHAR(50) NOT NULL,
                valor_propuesto JSONB NOT NULL,
                estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                CONSTRAINT ck_tickets_propuestas_ia_estado
                    CHECK (estado IN ('pendiente','confirmada','descartada','reemplazada'))
            )
            """
        )
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        conn.commit()
        conn.close()
        engine.dispose()


def _run_migration_fn(conn, fn) -> None:
    """Runs a migration's `upgrade`/`downgrade` (which call `op.get_bind()`
    internally) against `conn`'s own connection/transaction — mirrors
    `test_migration_triage_auto_apply_backfill.py`'s helper."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    ctx = MigrationContext.configure(conn)
    op_obj = Operations(ctx)
    op_obj._install_proxy()
    try:
        fn()
    finally:
        op_obj._remove_proxy()


@pytest.mark.postgres
class TestUpgradeAddsCorregidaAndValorCorregido:
    def test_upgrade_widens_estado_check_and_adds_column(self, pg_pre_migration_conn) -> None:
        conn = pg_pre_migration_conn
        migration = _load_migration()

        _run_migration_fn(conn, migration.upgrade)

        inspector = sa.inspect(conn)
        columns = {c["name"] for c in inspector.get_columns("tickets_propuestas_ia")}
        assert "valor_corregido" in columns

        # Real DATA proof, not schema introspection alone: a 'corregida'
        # row with a valid valor_corregido must insert cleanly.
        conn.execute(
            sa.text(
                "INSERT INTO tickets_propuestas_ia (campo, valor_propuesto, estado, valor_corregido) "
                "VALUES ('severidad', '{\"valor\": \"mayor\"}', 'corregida', 'menor')"
            )
        )
        row = conn.execute(sa.text("SELECT estado, valor_corregido FROM tickets_propuestas_ia")).one()
        assert row.estado == "corregida"
        assert row.valor_corregido == "menor"

    def test_upgrade_check_constraint_rejects_out_of_vocabulary_valor_corregido(self, pg_pre_migration_conn) -> None:
        conn = pg_pre_migration_conn
        migration = _load_migration()
        _run_migration_fn(conn, migration.upgrade)

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO tickets_propuestas_ia (campo, valor_propuesto, estado, valor_corregido) "
                    "VALUES ('urgencia', '{\"valor\": \"baja\"}', 'corregida', 'urgentisimo')"
                )
            )
        conn.rollback()  # clear the aborted transaction before this test's own fixture teardown


@pytest.mark.postgres
class TestDowngradeRemapsCorregidaLossily:
    def test_downgrade_remaps_corregida_row_to_descartada(self, pg_pre_migration_conn) -> None:
        """The bidirectional data verification the task explicitly
        requires: insert a 'corregida' row AFTER upgrade, run downgrade
        PROGRAMMATICALLY, re-query that SAME row and assert the remap —
        never trusting downgrade()'s exit code alone."""
        conn = pg_pre_migration_conn
        migration = _load_migration()
        _run_migration_fn(conn, migration.upgrade)

        conn.execute(
            sa.text(
                "INSERT INTO tickets_propuestas_ia (campo, valor_propuesto, estado, valor_corregido) "
                "VALUES ('severidad', '{\"valor\": \"mayor\"}', 'corregida', 'menor') RETURNING id"
            )
        )
        row_id = conn.execute(sa.text("SELECT id FROM tickets_propuestas_ia")).scalar_one()

        _run_migration_fn(conn, migration.downgrade)

        # Re-read the SAME row post-downgrade — data verification, not exit code.
        row = conn.execute(sa.text("SELECT estado FROM tickets_propuestas_ia WHERE id = :id"), {"id": row_id}).one()
        assert row.estado == "descartada"

        # The column itself is gone — re-upgrading cannot recover the
        # human's chosen value, exactly as the module docstring states.
        columns = {c["name"] for c in sa.inspect(conn).get_columns("tickets_propuestas_ia")}
        assert "valor_corregido" not in columns

    def test_downgrade_old_check_constraint_rejects_corregida_after_remap(self, pg_pre_migration_conn) -> None:
        """Proves the OLD (narrower) CHECK is genuinely back in place, not
        just that the column disappeared — a fresh INSERT attempting
        `estado='corregida'` post-downgrade must fail the same way it
        would have before this migration ever existed."""
        conn = pg_pre_migration_conn
        migration = _load_migration()
        _run_migration_fn(conn, migration.upgrade)
        _run_migration_fn(conn, migration.downgrade)

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO tickets_propuestas_ia (campo, valor_propuesto, estado) "
                    "VALUES ('severidad', '{\"valor\": \"mayor\"}', 'corregida')"
                )
            )
        conn.rollback()  # clear the aborted transaction before this test's own fixture teardown

    def test_downgrade_leaves_non_corregida_rows_untouched(self, pg_pre_migration_conn) -> None:
        """The remap must be scoped to `estado='corregida'` only — a
        ratified/discarded row sitting alongside it must survive
        downgrade unchanged."""
        conn = pg_pre_migration_conn
        migration = _load_migration()
        _run_migration_fn(conn, migration.upgrade)

        conn.execute(
            sa.text(
                "INSERT INTO tickets_propuestas_ia (campo, valor_propuesto, estado) "
                "VALUES ('urgencia', '{\"valor\": \"alta\"}', 'confirmada') RETURNING id"
            )
        )
        confirmada_id = conn.execute(
            sa.text("SELECT id FROM tickets_propuestas_ia WHERE estado = 'confirmada'")
        ).scalar_one()

        _run_migration_fn(conn, migration.downgrade)

        row = conn.execute(
            sa.text("SELECT estado FROM tickets_propuestas_ia WHERE id = :id"), {"id": confirmada_id}
        ).one()
        assert row.estado == "confirmada"  # untouched by the remap

"""Migration `20261007_ml_publications_quality`: competition, performance, moderation and visits state tables.

Runs inside a throwaway schema of the Postgres test DB. New tables only; no foreign key and no column
that points at a GBP/ERP table (data only from MercadoLibre).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261007_ml_publications_quality.py"

SHARED_COLUMNS = {
    "raw": "jsonb",
    "raw_hash": "bytea",
    "http_status": "smallint",
    "error_body": "jsonb",
    "last_error": "text",
    "first_seen_at": "timestamp with time zone",
    "fetched_at": "timestamp with time zone",
    "fetched_request_started_at": "timestamp with time zone",
    "never_existed": "boolean",
    "last_checked_at": "timestamp with time zone",
    "gone_at": "timestamp with time zone",
}

# table -> {typed column: postgres data_type}, fixed from the 2026-10-06 captures; every table is keyed by item_id.
TABLES = {
    "ml_item_competition": {
        "status": "text",
        "price_to_win": "numeric",
        "current_price": "numeric",
        "currency_id": "text",
        "consistent": "boolean",
    },
    "ml_item_performance": {
        "applicable": "boolean",
        "entity_type": "text",
        "entity_id": "text",
        "score": "numeric",
        "level": "text",
        "calculated_at": "timestamp with time zone",
    },
    "ml_item_moderations": {"has_moderation": "boolean"},
    "ml_item_visits": {
        "window_days": "integer",
        "total_visits": "integer",
        "date_from": "timestamp with time zone",
        "date_to": "timestamp with time zone",
    },
}
PARENT = "20261006_ml_metricas_permisos_pm"


def _load_migration():
    spec = importlib.util.spec_from_file_location("ml_publications_quality_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"mlpub_q_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
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


def _tables(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")).all()
    return {r[0] for r in rows}


def _columns(engine, table: str) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t"
            ),
            {"t": table},
        ).all()
    return {r[0]: r[1] for r in rows}


@pytest.mark.postgres
class TestMlPublicationsQualityMigration:
    def test_upgrade_creates_exactly_the_quality_tables(self, engine) -> None:
        _run(engine, "upgrade")
        assert _tables(engine) == set(TABLES)

    @pytest.mark.parametrize("table", sorted(TABLES))
    def test_shared_metadata_and_typed_columns(self, engine, table) -> None:
        _run(engine, "upgrade")
        columns = _columns(engine, table)
        for name, data_type in SHARED_COLUMNS.items():
            assert columns.get(name) == data_type, (table, name)
        for name, data_type in TABLES[table].items():
            assert columns.get(name) == data_type, (table, name)
        assert set(columns) == {"item_id", *SHARED_COLUMNS, *TABLES[table]}

    @pytest.mark.parametrize("table", sorted(TABLES))
    def test_primary_key_is_item_id(self, engine, table) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            pk = conn.execute(
                text(
                    "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    "AND a.attnum = ANY(i.indkey) WHERE i.indisprimary AND i.indrelid = CAST(:t AS regclass)"
                ),
                {"t": table},
            ).all()
        assert [r[0] for r in pk] == ["item_id"]

    def test_state_tables_use_fillfactor_85(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT relname, reloptions FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
                    "AND relkind = 'r'"
                )
            ).all()
        options = {name: opts or [] for name, opts in rows}
        for table in TABLES:
            assert "fillfactor=85" in options[table], table

    def test_defaults_and_no_foreign_keys_to_anything(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO ml_item_moderations (item_id) VALUES ('MLA1')"))
            row = conn.execute(
                text("SELECT never_existed, first_seen_at, has_moderation FROM ml_item_moderations")
            ).one()
            fks = conn.execute(
                text(
                    "SELECT 1 FROM pg_constraint WHERE contype = 'f' AND connamespace = current_schema()::regnamespace"
                )
            ).all()
        assert row[0] is False and row[1] is not None and row[2] is None
        assert fks == []
        for table in TABLES:
            assert not [c for c in _columns(engine, table) if "producto" in c or "erp" in c]

    def test_downgrade_removes_exactly_these_tables(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE unrelated (id int)"))
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        assert _tables(engine) == {"unrelated"}


def test_chains_from_the_previous_head_and_alembic_has_a_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migration = _load_migration()
    assert migration.down_revision == PARENT
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    directory = ScriptDirectory.from_config(cfg)
    # One head (alembic did not fork) that descends from this revision; not "this revision IS the head",
    # so a later migration on top keeps it green.
    heads = directory.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == migration.revision for rev in directory.walk_revisions("base", heads[0]))

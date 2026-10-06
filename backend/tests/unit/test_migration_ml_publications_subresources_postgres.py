"""Migration `20261006_ml_publications_subresources`: per-item / per-user-product sub-resource state tables.

Runs inside a throwaway schema of the Postgres test DB. New tables only; no foreign key
and no column that points at a GBP/ERP table (data only from MercadoLibre).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261006_ml_publications_subresources.py"

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

# table -> (key column, {typed column: postgres data_type}) fixed from the 2026-10-06 captures.
TABLES = {
    "ml_item_descriptions": (
        "item_id",
        {"plain_text_length": "integer", "ml_last_updated": "timestamp with time zone"},
    ),
    "ml_item_prices": (
        "item_id",
        {"standard_amount": "numeric", "currency_id": "text", "active_promotion_amount": "numeric"},
    ),
    "ml_item_sale_prices": (
        "item_id",
        {
            "price_id": "text",
            "amount": "numeric",
            "regular_amount": "numeric",
            "currency_id": "text",
            "campaign_id": "text",
            "promotion_id": "text",
            "promotion_type": "text",
        },
    ),
    "ml_item_seller_promotions": (
        "item_id",
        {"candidate_count": "integer", "started_count": "integer", "started_promotion_keys": "ARRAY"},
    ),
    "ml_user_products": (
        "user_product_id",
        {
            "family_id": "bigint",
            "name": "text",
            "domain_id": "text",
            "catalog_product_id": "text",
            "ml_last_updated": "timestamp with time zone",
        },
    ),
    "ml_user_product_stock": (
        "user_product_id",
        {"total_quantity": "integer", "ml_last_updated": "timestamp with time zone"},
    ),
    "ml_user_product_families": ("family_id", {"user_products_ids": "ARRAY"}),
}
FORBIDDEN_REFS = {"productos_erp", "tb_mercadolibre_items_publicados", "publicaciones_ml"}
FAMILY_ID = 7695306917964170  # > 2**52, must survive a round trip as bigint


def _load_migration():
    spec = importlib.util.spec_from_file_location("ml_publications_subresources_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"mlpub_sub_{uuid.uuid4().hex[:8]}"
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
class TestMlPublicationsSubresourcesMigration:
    def test_upgrade_creates_exactly_the_subresource_tables(self, engine) -> None:
        _run(engine, "upgrade")
        assert _tables(engine) == set(TABLES)

    @pytest.mark.parametrize("table", sorted(TABLES))
    def test_shared_metadata_and_typed_columns(self, engine, table) -> None:
        _run(engine, "upgrade")
        key, typed = TABLES[table]
        columns = _columns(engine, table)
        for name, data_type in SHARED_COLUMNS.items():
            assert columns.get(name) == data_type, (table, name)
        for name, data_type in typed.items():
            assert columns.get(name) == data_type, (table, name)
        assert key in columns
        assert set(columns) == {key, *SHARED_COLUMNS, *typed}

    @pytest.mark.parametrize("table", sorted(TABLES))
    def test_primary_key_is_the_entity_key(self, engine, table) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            pk = conn.execute(
                text(
                    "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    "AND a.attnum = ANY(i.indkey) WHERE i.indisprimary AND i.indrelid = CAST(:t AS regclass)"
                ),
                {"t": table},
            ).all()
        assert [r[0] for r in pk] == [TABLES[table][0]]

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

    def test_family_id_is_bigint_on_user_products_and_families_and_round_trips(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO ml_user_products (user_product_id, family_id) VALUES ('MLAU1', :f)"),
                {"f": FAMILY_ID},
            )
            conn.execute(
                text("INSERT INTO ml_user_product_families (family_id, user_products_ids) VALUES (:f, '{MLAU1}')"),
                {"f": FAMILY_ID},
            )
            assert conn.execute(text("SELECT family_id FROM ml_user_products")).scalar() == FAMILY_ID
            assert conn.execute(text("SELECT family_id FROM ml_user_product_families")).scalar() == FAMILY_ID

    def test_never_existed_defaults_false_and_first_seen_at_defaults_now(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO ml_item_descriptions (item_id) VALUES ('MLA1')"))
            row = conn.execute(text("SELECT never_existed, first_seen_at FROM ml_item_descriptions")).one()
        assert row[0] is False and row[1] is not None

    def test_no_foreign_keys_or_link_columns_to_gbp_erp_tables(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            fks = conn.execute(
                text(
                    "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
                    "WHERE contype = 'f' AND connamespace = current_schema()::regnamespace"
                )
            ).all()
        assert fks == []
        for table in TABLES:
            assert not [c for c in _columns(engine, table) if "producto" in c or "erp" in c]

    def test_downgrade_removes_exactly_these_tables(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE unrelated (id int)"))
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        assert _tables(engine) == {"unrelated"}


def test_revises_the_core_migration_and_alembic_has_a_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migration = _load_migration()
    assert migration.down_revision == "20261006_ml_publications_core"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1

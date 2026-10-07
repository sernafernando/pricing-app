"""Migration `20261006_ml_publications_product_links`: the product link table (design D20).

Runs inside a throwaway schema of the Postgres test DB. New table only; the product id is stored
WITHOUT a foreign key to `productos_erp` (the ERP sync rewrites that table).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261006_ml_publications_product_links.py"

TABLE = "ml_item_product_links"
COLUMNS = {
    "item_id": "text",
    "variation_id": "bigint",
    "source": "text",
    "match_status": "text",
    "producto_item_id": "integer",
    "matched_sku": "text",
    "sku_field": "text",
    "candidate_ids": "ARRAY",
    "suggested_producto_item_id": "integer",
    "suggestion_status": "text",
    "suggestion_candidates": "smallint",
    "evaluated_sku_key": "text",
    "evaluated_at": "timestamp with time zone",
    "linked_by": "integer",
    "linked_at": "timestamp with time zone",
    "note": "text",
    "first_seen_at": "timestamp with time zone",
    "updated_at": "timestamp with time zone",
}
INSERT = (
    "INSERT INTO ml_item_product_links (item_id, variation_id, source, match_status, producto_item_id, linked_at) "
    "VALUES (:item, :variation, :source, :status, :product, now())"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("ml_publications_product_links_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"mlpub_lnk_{uuid.uuid4().hex[:8]}"
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


def _row(item="MLA1", variation=0, source="sku_auto", status="unmatched", product=None) -> dict:
    return {"item": item, "variation": variation, "source": source, "status": status, "product": product}


@pytest.mark.postgres
class TestProductLinksMigration:
    def test_upgrade_creates_exactly_the_link_table_with_its_columns(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            tables = {
                r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))
            }
            columns = dict(
                conn.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = :t"
                    ),
                    {"t": TABLE},
                ).all()
            )
        assert tables == {TABLE}
        assert columns == COLUMNS

    def test_primary_key_is_item_and_variation_and_variation_defaults_to_the_item_level_sentinel(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            pk = conn.execute(
                text(
                    "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    "AND a.attnum = ANY(i.indkey) WHERE i.indisprimary AND i.indrelid = CAST(:t AS regclass) "
                    "ORDER BY a.attnum"
                ),
                {"t": TABLE},
            ).all()
            conn.execute(
                text(
                    "INSERT INTO ml_item_product_links (item_id, source, match_status, linked_at) "
                    "VALUES ('MLA1', 'sku_auto', 'unmatched', now())"
                )
            )
            variation = conn.execute(text("SELECT variation_id FROM ml_item_product_links")).scalar()
        assert [r[0] for r in pk] == ["item_id", "variation_id"]
        assert variation == 0

    @pytest.mark.parametrize(
        "bad",
        [
            _row(variation=-1),
            _row(source="robot"),
            _row(status="maybe"),
            _row(status="linked", product=None),  # linked <=> product id
            _row(status="unmatched", product=7),
            _row(source="manual_none", status="unmatched"),  # manual_none => no_product
        ],
    )
    def test_check_constraints_reject_inconsistent_rows(self, engine, bad) -> None:
        _run(engine, "upgrade")
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(INSERT), bad)

    def test_consistent_rows_of_every_shape_are_accepted(self, engine) -> None:
        _run(engine, "upgrade")
        rows = [
            _row("MLA1", 0, "sku_auto", "linked", 10),
            _row("MLA1", 5, "manual", "linked", 11),
            _row("MLA2", 0, "manual_none", "no_product"),
            _row("MLA3", 0, "sku_auto", "conflict"),
        ]
        with engine.begin() as conn:
            for row in rows:
                conn.execute(text(INSERT), row)
            assert conn.execute(text("SELECT count(*) FROM ml_item_product_links")).scalar() == 4

    def test_the_documented_indexes_exist_and_the_manual_differs_one_is_partial(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            indexes = dict(
                conn.execute(
                    text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()")
                ).all()
            )
        by_columns = {
            definition.split("USING btree ", 1)[1] for definition in indexes.values() if "USING btree" in definition
        }
        assert "(match_status, source)" in by_columns
        assert "(producto_item_id)" in by_columns
        partial = [d for d in indexes.values() if "WHERE" in d]
        assert len(partial) == 1
        assert "sku_auto" in partial[0] and "suggested_producto_item_id" in partial[0]

    def test_no_foreign_key_to_the_erp_product_table(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE productos_erp (item_id integer PRIMARY KEY)"))
        _run(engine, "upgrade")
        with engine.connect() as conn:
            fks = conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE contype = 'f' AND connamespace = current_schema()::regnamespace"
                )
            ).all()
        assert fks == []

    def test_fillfactor_85(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            options = conn.execute(
                text("SELECT reloptions FROM pg_class WHERE oid = CAST(:t AS regclass)"), {"t": TABLE}
            ).scalar()
        assert "fillfactor=85" in options

    def test_downgrade_removes_exactly_this_table(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE unrelated (id int)"))
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        with engine.connect() as conn:
            tables = {
                r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))
            }
        assert tables == {"unrelated"}


def test_revises_the_subresources_migration_and_alembic_has_a_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migration = _load_migration()
    assert migration.down_revision == "20261006_ml_publications_subresources"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1

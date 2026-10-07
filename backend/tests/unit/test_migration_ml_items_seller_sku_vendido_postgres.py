"""Migration `20261007_ml_items_seller_sku_vendido`: the SKU an order item was sold with.

Runs inside a throwaway schema of the Postgres test DB, over a minimal `ml_order_items_ops` that
already holds rows (the backfill must copy `seller_sku`, and leave SKU-less rows NULL).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REVISION = "20261007_ml_items_seller_sku_vendido"
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / f"{_REVISION}.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("ml_items_seller_sku_vendido_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"skuv_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE ml_order_items_ops (id serial PRIMARY KEY, seller_sku varchar(60))"))
        conn.execute(text("INSERT INTO ml_order_items_ops (seller_sku) VALUES ('1214'), (NULL), ('ABC-9')"))
    try:
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def _run(engine, step: str, migration=None) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = migration or _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(migration, step)()


def _vendidos(engine) -> list:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT seller_sku_vendido FROM ml_order_items_ops ORDER BY id"))]


def test_the_revision_is_in_a_single_head_chain() -> None:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {rev.revision for rev in script.walk_revisions(base="base", head=heads[0])}


@pytest.mark.postgres
class TestSellerSkuVendidoMigration:
    def test_upgrade_backfills_from_seller_sku_and_leaves_skuless_rows_null(self, engine) -> None:
        _run(engine, "upgrade")
        assert _vendidos(engine) == ["1214", None, "ABC-9"]

    def test_upgrade_adds_the_indexed_nullable_column(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND table_name = 'ml_order_items_ops' AND column_name = 'seller_sku_vendido'"
                )
            ).scalar()
            index = conn.execute(
                text("SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND indexname = :n"),
                {"n": "ix_ml_order_items_ops_seller_sku_vendido"},
            ).scalar()
        assert nullable == "YES"
        assert index == 1

    def test_backfill_spans_several_batches(self, engine, monkeypatch) -> None:
        migration = _load_migration()
        monkeypatch.setattr(migration, "_BATCH", 1)
        _run(engine, "upgrade", migration)
        assert _vendidos(engine) == ["1214", None, "ABC-9"]

    def test_downgrade_drops_the_column_and_its_index(self, engine) -> None:
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        with engine.connect() as conn:
            cols = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'ml_order_items_ops'"
                    )
                )
            }
        assert "seller_sku_vendido" not in cols

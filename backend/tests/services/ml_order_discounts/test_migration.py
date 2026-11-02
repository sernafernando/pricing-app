"""ml-ads-cupones-display T3a -- the per-sale discounts tables and their migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.services.ml_ads.test_account_level_migration import _BACKEND_ROOT, _script_directory

_REVISION = "20261228_ml_order_discounts"
TABLES = {
    "ml_order_discounts": ({"order_id", "status", "http_status", "body", "attempts", "fetched_at"}, ["order_id"]),
    "ml_order_discount_lines": (
        {
            "id",
            "order_id",
            "detail_index",
            "item_index",
            "type",
            "coupon_id",
            "campaign_id",
            "meli_campaign",
            "offer_id",
            "funding_mode",
            "item_id",
            "element_id",
            "quantity",
            "amount_seller",
            "amount_total",
        },
        ["id"],
    ),
    "ml_order_discounts_state": ({"id", "consecutive_429", "backoff_until"}, ["id"]),
}


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_order_discounts_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261227_sell_in_modos_producto"
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}


def test_exact_columns_and_primary_keys() -> None:
    from app.core.database import Base
    from app.models import ml_order_discounts  # noqa: F401

    for name, (columns, primary_key) in TABLES.items():
        table = Base.metadata.tables[name]
        assert {c.name for c in table.columns} == columns, name
        assert [c.name for c in table.primary_key.columns] == primary_key, name


@pytest.mark.postgres
def test_upgrade_matches_the_models_and_downgrade_drops_exactly_them(pg_engine) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.core.database import Base
    from tests.services.ml_order_discounts.conftest import restore_pg_types

    restore_pg_types()
    migration = _load_migration()
    drop = "DROP TABLE IF EXISTS " + ", ".join(TABLES) + " CASCADE"
    with pg_engine.begin() as conn:
        conn.execute(sa.text(drop))
    with pg_engine.connect() as conn:
        op_obj = Operations(MigrationContext.configure(conn))
        op_obj._install_proxy()
        try:
            before = set(sa.inspect(conn).get_table_names())
            migration.upgrade()
            conn.commit()
            inspector = sa.inspect(conn)
            assert set(inspector.get_table_names()) == before | set(TABLES)
            for name, (columns, primary_key) in TABLES.items():
                migrated = {c["name"]: c for c in inspector.get_columns(name)}
                assert set(migrated) == columns
                assert inspector.get_pk_constraint(name)["constrained_columns"] == primary_key
                for column in Base.metadata.tables[name].columns:
                    compiled = migrated[column.name]["type"].compile(conn.dialect)
                    assert compiled == column.type.compile(conn.dialect), (name, column.name)
                    assert migrated[column.name]["nullable"] == column.nullable, (name, column.name)
            indexes = {i["name"] for i in inspector.get_indexes("ml_order_discount_lines")}
            assert {"ix_ml_order_discount_lines_order_id", "ix_ml_order_discount_lines_coupon_id"} <= indexes
            migration.downgrade()
            conn.commit()
            assert set(sa.inspect(conn).get_table_names()) == before
        finally:
            op_obj._remove_proxy()
            with pg_engine.begin() as cleanup:
                cleanup.execute(sa.text(drop))

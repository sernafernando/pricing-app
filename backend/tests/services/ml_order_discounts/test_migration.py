"""ml-ads-cupones-display T3a -- the per-sale discounts tables and their migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.services.ml_ads.test_account_level_migration import _BACKEND_ROOT, _script_directory

_REVISION = "20261228_ml_order_discounts"
_INDEX_REVISION = "20261228_ml_pay_ops_coupon_idx"
_INDEX = "ix_ml_payments_ops_coupon_order_id"
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


def _path(revision: str) -> Path:
    return Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{revision}.py"


def _load_migration(revision: str = _REVISION):
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", _path(revision))
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


def test_the_payments_index_has_its_own_revision_after_the_tables() -> None:
    """A failed CONCURRENTLY build after the tables were committed left the tables migration unrerunnable
    (DuplicateTable): the index lives in its own revision, so a rerun only repeats the index."""
    script = _script_directory()
    revision = script.get_revision(_INDEX_REVISION)
    assert revision is not None
    assert revision.down_revision == _REVISION
    assert _INDEX_REVISION in {r.revision for r in script.walk_revisions(base="base", head=script.get_heads()[0])}


def test_the_tables_migration_builds_no_index_on_payments() -> None:
    source = _path(_REVISION).read_text()
    assert "ml_payments_ops" not in source.split('"""', 2)[2]
    assert "autocommit_block" not in source


def test_the_pending_query_has_a_partial_index_on_coupon_payments() -> None:
    from app.core.database import Base
    from app.models import ml_order_discounts  # noqa: F401

    (index,) = [
        i for i in Base.metadata.tables["ml_payments_ops"].indexes if i.name == "ix_ml_payments_ops_coupon_order_id"
    ]
    assert [c.name for c in index.columns] == ["order_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "ml_payments_ops.coupon_amount > :coupon_amount_1"


def test_the_models_are_registered_in_the_models_package() -> None:
    """alembic/env.py builds target_metadata from `from app.models import *`: a missing model would be dropped by
    the next autogenerate."""
    import app.models as models

    assert {"MlOrderDiscounts", "MlOrderDiscountLine", "MlOrderDiscountsState"} <= set(models.__all__)


def test_the_payments_index_is_built_concurrently_with_a_lock_timeout_and_cleans_an_invalid_leftover() -> None:
    source = _path(_INDEX_REVISION).read_text()
    assert "autocommit_block()" in source
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX}" in source
    assert "ON ml_payments_ops (order_id) WHERE coupon_amount > 0" in source
    assert "lock_timeout" in source and "RESET lock_timeout" in source
    assert "indisvalid" in source and "DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}" in source


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
    from app.models.ml_payments import MlPaymentOps
    from tests.services.ml_order_discounts.conftest import restore_pg_types

    restore_pg_types()
    migration = _load_migration()
    index_migration = _load_migration(_INDEX_REVISION)
    drop = "DROP TABLE IF EXISTS " + ", ".join(TABLES) + " CASCADE"
    MlPaymentOps.__table__.create(bind=pg_engine, checkfirst=True)  # the partial index is on this table
    with pg_engine.begin() as conn:
        conn.execute(sa.text(drop))
        conn.execute(sa.text("DROP INDEX IF EXISTS ix_ml_payments_ops_coupon_order_id"))
    with pg_engine.connect() as conn:
        # The payments index (its own revision) is built CONCURRENTLY in an `autocommit_block`, which needs the migration's own
        # transaction: same pattern as tests/unit/test_migration_ml_items_last_trigger_index.py.
        ctx = MigrationContext.configure(conn)
        try:
            before = set(sa.inspect(conn).get_table_names())
            conn.commit()
            with Operations.context(ctx), ctx.begin_transaction():
                migration.upgrade()
            with Operations.context(ctx), ctx.begin_transaction():
                index_migration.upgrade()
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
            predicate = conn.execute(
                sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_ml_payments_ops_coupon_order_id'")
            ).scalar()
            assert predicate is not None and "WHERE (coupon_amount > (0)" in predicate
            conn.commit()
            with Operations.context(ctx), ctx.begin_transaction():
                index_migration.downgrade()
            with Operations.context(ctx), ctx.begin_transaction():
                migration.downgrade()
            assert set(sa.inspect(conn).get_table_names()) == before
            assert "ix_ml_payments_ops_coupon_order_id" not in {
                i["name"] for i in sa.inspect(conn).get_indexes("ml_payments_ops")
            }
        finally:
            conn.rollback()
            with pg_engine.begin() as cleanup:
                cleanup.execute(sa.text(drop))
                cleanup.execute(sa.text("DROP INDEX IF EXISTS ix_ml_payments_ops_coupon_order_id"))


@pytest.mark.postgres
def test_an_invalid_index_left_by_a_failed_build_is_dropped_and_rebuilt(pg_engine) -> None:
    """A cancelled or failed CONCURRENTLY build leaves an INVALID index with the same name, which IF NOT EXISTS
    alone would accept. A failed unique build leaves one deterministically."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.models.ml_payments import MlPaymentOps

    index_migration = _load_migration(_INDEX_REVISION)
    MlPaymentOps.__table__.create(bind=pg_engine, checkfirst=True)
    with pg_engine.begin() as conn:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX}"))
        conn.execute(sa.text("DELETE FROM ml_payments_ops"))
        conn.execute(
            sa.text(
                "INSERT INTO ml_payments_ops (payment_id, order_id, status, coupon_amount) "
                "VALUES (1, 7, 'approved', 10), (2, 7, 'approved', 10)"
            )
        )
    autocommit = pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        with pytest.raises(sa.exc.IntegrityError):
            autocommit.execute(
                sa.text(
                    f"CREATE UNIQUE INDEX CONCURRENTLY {_INDEX} ON ml_payments_ops (order_id) WHERE coupon_amount > 0"
                )
            )
        valid = sa.text(
            "SELECT i.indisvalid, i.indisunique FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name"
        )
        assert autocommit.execute(valid, {"name": _INDEX}).one() == (False, True)
        with pg_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                index_migration.upgrade()
            conn.commit()
        assert autocommit.execute(valid, {"name": _INDEX}).one() == (True, False)
    finally:
        autocommit.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX}"))
        autocommit.execute(sa.text("DELETE FROM ml_payments_ops"))
        autocommit.close()

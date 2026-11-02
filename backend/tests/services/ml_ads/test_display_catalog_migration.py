"""ml-ads-cupones-display T1 (S6) -- the Display campaign catalog table and its migration.

Same layers as `test_account_level_migration`: graph (single head, ancestor), exact columns and primary key,
and the upgrade/downgrade round trip creating and dropping exactly this table.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.services.ml_ads.test_account_level_migration import _BACKEND_ROOT, _script_directory

_REVISION = "20261226_ml_ads_display_catalog"
TABLE = "ml_ads_display_campaigns"
EXPECTED_COLUMNS = {
    "advertiser_id",
    "campaign_id",
    "name",
    "type",
    "status",
    "goal",
    "site_id",
    "start_date",
    "end_date",
    "raw",
    "updated_at",
}
NOT_NULL = {"advertiser_id", "campaign_id", "raw", "updated_at"}


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_ads_display_catalog_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert isinstance(revision.down_revision, str), "exactly one parent, never a branch point"
    assert script.get_revision(revision.down_revision) is not None
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}


def test_exact_columns_primary_key_and_nullability() -> None:
    from app.core.database import Base

    table = Base.metadata.tables[TABLE]
    assert {c.name for c in table.columns} == EXPECTED_COLUMNS
    assert [c.name for c in table.primary_key.columns] == ["advertiser_id", "campaign_id"]
    assert {c.name for c in table.columns if not c.nullable} == NOT_NULL


@pytest.mark.postgres
def test_upgrade_matches_the_model_and_downgrade_drops_exactly_it(pg_engine) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.core.database import Base
    from tests.services.ml_ads.conftest import restore_pg_types

    restore_pg_types()
    migration = _load_migration()
    with pg_engine.begin() as conn:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {TABLE} CASCADE"))
    with pg_engine.connect() as conn:
        op_obj = Operations(MigrationContext.configure(conn))
        op_obj._install_proxy()
        try:
            before = set(sa.inspect(conn).get_table_names())
            migration.upgrade()
            conn.commit()
            inspector = sa.inspect(conn)
            assert set(inspector.get_table_names()) == before | {TABLE}
            migrated = {c["name"]: c for c in inspector.get_columns(TABLE)}
            assert set(migrated) == EXPECTED_COLUMNS
            assert inspector.get_pk_constraint(TABLE)["constrained_columns"] == ["advertiser_id", "campaign_id"]
            for column in Base.metadata.tables[TABLE].columns:
                compiled = migrated[column.name]["type"].compile(conn.dialect)
                assert compiled == column.type.compile(conn.dialect), column.name
                assert migrated[column.name]["nullable"] == column.nullable, column.name
            assert "now()" in migrated["updated_at"]["default"]
            migration.downgrade()
            conn.commit()
            assert set(sa.inspect(conn).get_table_names()) == before
        finally:
            op_obj._remove_proxy()
            with pg_engine.begin() as cleanup:
                cleanup.execute(sa.text(f"DROP TABLE IF EXISTS {TABLE} CASCADE"))

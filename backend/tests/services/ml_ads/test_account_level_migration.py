"""ml-billing-balance PR 3-i -- account-level ads tables and their migration (design "Schema", D11).

Graph layer (always runs): single head, the revision is its ancestor. Postgres layer: exact columns and
primary keys, no cached sums, and the upgrade/downgrade round trip dropping exactly the two tables.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.services.ml_ads.test_models_migration import CACHED_SUM_NAME

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_REVISION = "20261014_ml_ads_account_level"

EXPECTED_COLUMNS = {
    "ml_ads_display_campaign_days": {
        "advertiser_id",
        "campaign_id",
        "day",
        "consumed_budget",
        "prints",
        "clicks",
        "reach",
        "raw",
        "fetched_at",
    },
    "ml_ads_brand_days": {"advertiser_id", "day", "cost", "prints", "clicks", "raw", "fetched_at"},
}
EXPECTED_PKS = {
    "ml_ads_display_campaign_days": ["advertiser_id", "campaign_id", "day"],
    "ml_ads_brand_days": ["advertiser_id", "day"],
}
TABLES = list(EXPECTED_COLUMNS)


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_ads_account_level_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_revision_has_one_registered_parent(self) -> None:
        # The parent is not pinned by name: a rebase onto a main that added migrations moves it.
        script = _script_directory()
        revision = script.get_revision(_REVISION)
        assert revision is not None
        assert isinstance(revision.down_revision, str), "exactly one parent, never a branch point"
        assert script.get_revision(revision.down_revision) is not None

    def test_is_single_head_and_revision_is_its_ancestor(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        assert _REVISION in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}


class TestModels:
    @pytest.mark.parametrize("table_name", TABLES)
    def test_exact_columns_primary_key_and_no_cached_sums(self, table_name: str) -> None:
        from app.core.database import Base

        table = Base.metadata.tables[table_name]
        assert {c.name for c in table.columns} == EXPECTED_COLUMNS[table_name]
        assert [c.name for c in table.primary_key.columns] == EXPECTED_PKS[table_name]
        assert [c.name for c in table.columns if CACHED_SUM_NAME.search(c.name)] == []


@pytest.mark.postgres
class TestRoundTrip:
    def test_upgrade_creates_both_tables_and_downgrade_drops_exactly_them(self, pg_engine) -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        from app.core.database import Base
        from tests.services.ml_ads.conftest import restore_pg_types

        restore_pg_types()
        migration = _load_migration()
        with pg_engine.begin() as conn:
            for name in TABLES:
                conn.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))

        with pg_engine.connect() as conn:
            op_obj = Operations(MigrationContext.configure(conn))
            op_obj._install_proxy()
            try:
                before = set(sa.inspect(conn).get_table_names())
                migration.upgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                for name in TABLES:
                    migrated = {c["name"]: c for c in inspector.get_columns(name)}
                    assert set(migrated) == EXPECTED_COLUMNS[name]
                    assert inspector.get_pk_constraint(name)["constrained_columns"] == EXPECTED_PKS[name]
                    for column in Base.metadata.tables[name].columns:
                        assert migrated[column.name]["type"].compile(conn.dialect) == column.type.compile(
                            conn.dialect
                        ), (name, column.name)
                        assert migrated[column.name]["nullable"] == column.nullable, (name, column.name)

                migration.downgrade()
                conn.commit()
                assert set(sa.inspect(conn).get_table_names()) == before
            finally:
                op_obj._remove_proxy()
                with pg_engine.begin() as cleanup:
                    for name in TABLES:
                        cleanup.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))

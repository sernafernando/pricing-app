"""ml-ads-campaigns -- the campaign tables and their migration (same layers as `test_account_level_migration`).

The migrated columns must equal the models' exactly (names, types, nullability); the models follow the capture.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.services.ml_ads.test_account_level_migration import _BACKEND_ROOT, _script_directory
from tests.services.ml_ads.test_models_migration import CACHED_SUM_NAME

_REVISION = "20261029_ml_ads_campaigns"

EXPECTED_PKS = {
    "ml_ads_campaigns": ["advertiser_id", "campaign_id"],
    "ml_ads_campaign_days": ["advertiser_id", "campaign_id", "day"],
}
TABLES = list(EXPECTED_PKS)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_ads_campaigns_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    revision = script.get_revision(_REVISION)
    assert isinstance(revision.down_revision, str), "exactly one parent, never a branch point"
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}


@pytest.mark.parametrize("table_name", TABLES)
def test_primary_key_and_no_cached_sums(table_name: str) -> None:
    from app.core.database import Base

    table = Base.metadata.tables[table_name]
    assert [c.name for c in table.primary_key.columns] == EXPECTED_PKS[table_name]
    assert [c.name for c in table.columns if CACHED_SUM_NAME.search(c.name)] == []


@pytest.mark.postgres
def test_upgrade_matches_the_models_and_downgrade_drops_exactly_them(pg_engine) -> None:
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
                assert inspector.get_pk_constraint(name)["constrained_columns"] == EXPECTED_PKS[name]
                for column in Base.metadata.tables[name].columns:
                    compiled = migrated[column.name]["type"].compile(conn.dialect)
                    assert compiled == column.type.compile(conn.dialect), (name, column.name)
                    assert migrated[column.name]["nullable"] == column.nullable, (name, column.name)
                assert set(migrated) == {c.name for c in Base.metadata.tables[name].columns}
            migration.downgrade()
            conn.commit()
            assert set(sa.inspect(conn).get_table_names()) == before
        finally:
            op_obj._remove_proxy()
            with pg_engine.begin() as cleanup:
                for name in TABLES:
                    cleanup.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))

"""ml-billing-balance PR 1a -- ads tables and their migration (spec ADS-1, ADS-3, ADS-4; design "Schema").

Graph layer (always runs): the migration is a single-head continuation of the chain.
Postgres layer (`@pytest.mark.postgres`): exact primary keys, CHECK sets, no cached-sum columns, and
the upgrade/downgrade round trip against the real DDL.
"""

from __future__ import annotations

import importlib.util
import os
import re
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from app.models.ml_ads import MlAdsAdGroupDay, MlAdsDayLedger, MlAdsItemDay

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_REVISION = "20261008_ml_ads_product_ads"

EXPECTED_COLUMNS = {
    "ml_ads_day_ledger": {
        "source",
        "advertiser_id",
        "day",
        "status",
        "groups_offset",
        "summary_cost",
        "summary_raw",
        "attempts",
        "attempts_day",
        "mismatch_laps",
        "last_error",
        "fetch_started_at",
        "closed_at",
        "verified_at",
        "updated_at",
        "final",
    },
    "ml_ads_ad_group_days": {
        "advertiser_id",
        "ad_group_id",
        "day",
        "campaign_id",
        "ad_group_type",
        "external_id",
        "cost",
        "direct_amount",
        "indirect_amount",
        "clicks",
        "prints",
        "units_quantity",
        "drill_status",
        "ads_offset",
        "raw",
        "fetched_at",
    },
    "ml_ads_item_days": {
        "advertiser_id",
        "ad_group_id",
        "item_id",
        "day",
        "campaign_id",
        "cost",
        "direct_amount",
        "indirect_amount",
        "organic_amount",
        "clicks",
        "direct_units",
        "indirect_units",
        "organic_units",
        "prints",
        "raw",
        "fetched_at",
    },
}
EXPECTED_PKS = {
    "ml_ads_day_ledger": ["source", "advertiser_id", "day"],
    "ml_ads_ad_group_days": ["advertiser_id", "ad_group_id", "day"],
    "ml_ads_item_days": ["advertiser_id", "ad_group_id", "item_id", "day"],
}
ADS_TABLE_NAMES = list(EXPECTED_COLUMNS)
# ADS-4 "No cached sum": ML's own reported figures (`summary_cost`, a group's `cost`) are facts; a sum WE
# computed over rows must never be stored.
CACHED_SUM_NAME = re.compile(r"(^|_)(sum|total|stored|computed|cached)(_|$)|^(groups|items)_cost$")


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_ads_product_ads_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
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
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain, f"{_REVISION!r} is not an ancestor of the single head {heads[0]!r}"


class TestModelsDeclareTheDesignedSchema:
    @pytest.mark.parametrize("table_name", ADS_TABLE_NAMES)
    def test_exact_columns_and_primary_key(self, table_name: str) -> None:
        from app.core.database import Base

        table = Base.metadata.tables[table_name]
        assert {c.name for c in table.columns} == EXPECTED_COLUMNS[table_name]
        assert [c.name for c in table.primary_key.columns] == EXPECTED_PKS[table_name]

    @pytest.mark.parametrize("table_name", ADS_TABLE_NAMES)
    def test_no_cached_sum_columns(self, table_name: str) -> None:
        from app.core.database import Base

        offenders = [c.name for c in Base.metadata.tables[table_name].columns if CACHED_SUM_NAME.search(c.name)]
        assert offenders == []

    def test_guard_regex_catches_the_names_it_exists_for(self) -> None:
        # Triangulation for the guard above: it would fail the day one of these appears.
        for name in ("groups_cost", "items_cost", "ads_cost_sum", "stored_sum", "cost_total", "computed_cost"):
            assert CACHED_SUM_NAME.search(name), name
        for name in ("summary_cost", "cost", "direct_amount", "organic_units"):
            assert not CACHED_SUM_NAME.search(name), name


@pytest.mark.postgres
class TestConstraintsOnPostgres:
    @pytest.mark.parametrize("status", ["fetching", "refetch", "closed", "mismatch", "error", "unavailable"])
    def test_ledger_accepts_every_designed_status(self, pg_ads_db, status: str) -> None:
        pg_ads_db.add(MlAdsDayLedger(source="product_ads", advertiser_id=1, day=date(2026, 10, 5), status=status))
        pg_ads_db.flush()

        stored = pg_ads_db.get(MlAdsDayLedger, ("product_ads", 1, date(2026, 10, 5)))
        assert stored.status == status
        assert (stored.groups_offset, stored.attempts, stored.mismatch_laps, stored.final) == (0, 0, 0, False)

    def test_ledger_rejects_a_status_outside_the_set(self, pg_ads_db) -> None:
        pg_ads_db.add(MlAdsDayLedger(source="product_ads", advertiser_id=1, day=date(2026, 10, 5), status="done"))
        with pytest.raises(IntegrityError):
            pg_ads_db.flush()

    @pytest.mark.parametrize("drill_status", ["not_needed", "pending", "done", "mismatch"])
    def test_ad_group_accepts_every_designed_drill_status(self, pg_ads_db, drill_status: str) -> None:
        pg_ads_db.add(
            MlAdsAdGroupDay(
                advertiser_id=1, ad_group_id=2678077237, day=date(2026, 10, 5), drill_status=drill_status, raw={}
            )
        )
        pg_ads_db.flush()

        stored = pg_ads_db.get(MlAdsAdGroupDay, (1, 2678077237, date(2026, 10, 5)))
        assert stored.drill_status == drill_status
        assert stored.ads_offset == 0

    def test_ad_group_rejects_a_drill_status_outside_the_set(self, pg_ads_db) -> None:
        pg_ads_db.add(
            MlAdsAdGroupDay(advertiser_id=1, ad_group_id=2, day=date(2026, 10, 5), drill_status="skipped", raw={})
        )
        with pytest.raises(IntegrityError):
            pg_ads_db.flush()

    def test_item_day_defaults_to_zero_metrics_and_keeps_a_big_ad_group_id(self, pg_ads_db) -> None:
        pg_ads_db.add(
            MlAdsItemDay(advertiser_id=1, ad_group_id=2678077237, item_id="MLA1", day=date(2026, 10, 5), raw={})
        )
        pg_ads_db.flush()

        stored = pg_ads_db.get(MlAdsItemDay, (1, 2678077237, "MLA1", date(2026, 10, 5)))
        assert stored.ad_group_id == 2678077237  # above 2**31: BigInteger, not Integer
        assert (stored.cost, stored.organic_units, stored.prints) == (0, 0, 0)

    def test_same_item_on_two_ad_groups_is_two_rows(self, pg_ads_db) -> None:
        for group in (10, 11):
            pg_ads_db.add(
                MlAdsItemDay(advertiser_id=1, ad_group_id=group, item_id="MLA1", day=date(2026, 10, 5), raw={})
            )
        pg_ads_db.flush()

        count = pg_ads_db.execute(sa.text("SELECT count(*) FROM ml_ads_item_days")).scalar_one()
        assert count == 2


@pytest.mark.postgres
class TestMigrationRoundTrip:
    def test_upgrade_creates_the_three_tables_and_downgrade_drops_exactly_them(self, pg_engine) -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        migration = _load_migration()
        with pg_engine.begin() as conn:
            for name in reversed(ADS_TABLE_NAMES):
                conn.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))

        with pg_engine.connect() as conn:
            op_obj = Operations(MigrationContext.configure(conn))
            op_obj._install_proxy()
            try:
                before = set(sa.inspect(conn).get_table_names())
                migration.upgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                for name in ADS_TABLE_NAMES:
                    assert {c["name"] for c in inspector.get_columns(name)} == EXPECTED_COLUMNS[name]
                    assert inspector.get_pk_constraint(name)["constrained_columns"] == EXPECTED_PKS[name]
                ledger_index = {i["name"]: i for i in inspector.get_indexes("ml_ads_day_ledger")}
                assert ledger_index["ix_ml_ads_day_ledger_open"]["column_names"] == ["source", "status"]
                assert {c["name"] for c in inspector.get_check_constraints("ml_ads_day_ledger")} == {
                    "ck_ml_ads_day_ledger_status"
                }
                assert {c["name"] for c in inspector.get_check_constraints("ml_ads_ad_group_days")} == {
                    "ck_ml_ads_ad_group_days_drill_status"
                }
                group_index = {i["name"] for i in inspector.get_indexes("ml_ads_ad_group_days")}
                assert "ix_ml_ads_ad_group_days_adv_day_drill" in group_index
                item_index = {i["name"] for i in inspector.get_indexes("ml_ads_item_days")}
                assert "ix_ml_ads_item_days_day_item" in item_index

                migration.downgrade()
                conn.commit()
                after = set(sa.inspect(conn).get_table_names())
                assert after == before, "downgrade must drop exactly what upgrade added"
            finally:
                op_obj._remove_proxy()
                with pg_engine.begin() as cleanup:
                    for name in reversed(ADS_TABLE_NAMES):
                        cleanup.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))

    def test_migration_columns_match_the_models(self, pg_engine) -> None:
        """The hand-written migration and the ORM models describe the same columns and types."""
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        from app.core.database import Base
        from tests.services.ml_ads.conftest import restore_pg_types

        restore_pg_types()
        migration = _load_migration()
        with pg_engine.begin() as conn:
            for name in reversed(ADS_TABLE_NAMES):
                conn.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))
        with pg_engine.connect() as conn:
            op_obj = Operations(MigrationContext.configure(conn))
            op_obj._install_proxy()
            try:
                migration.upgrade()
                conn.commit()
                inspector = sa.inspect(conn)
                for name in ADS_TABLE_NAMES:
                    migrated = {c["name"]: c for c in inspector.get_columns(name)}
                    for column in Base.metadata.tables[name].columns:
                        assert migrated[column.name]["type"].compile(conn.dialect) == column.type.compile(
                            conn.dialect
                        ), (
                            name,
                            column.name,
                        )
                        assert migrated[column.name]["nullable"] == column.nullable, (name, column.name)
            finally:
                op_obj._remove_proxy()
                with pg_engine.begin() as cleanup:
                    for name in reversed(ADS_TABLE_NAMES):
                        cleanup.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))

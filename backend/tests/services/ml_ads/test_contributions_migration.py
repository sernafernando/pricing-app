"""ml-ads-brand-contribution T1a -- the `ml_ads_campaign_contributions` migration.

It runs inside a throwaway schema of the Postgres test DB and is compared with the same table built from the ORM;
the CHECK rules are proven at the database.
"""

from __future__ import annotations

import importlib.util
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.database import Base
from tests.services.ml_ads.test_account_level_migration import _script_directory

REVISION = "20261113_ml_ads_campaign_contributions"
TABLE = "ml_ads_campaign_contributions"
_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{REVISION}.py"
_INSERT = (
    f"INSERT INTO {TABLE} (advertiser_id, campaign_id, kind, value, date_from, date_to, created_by_id, "
    "updated_by_id) VALUES (714700, 351001, :kind, :value, :desde, :hasta, 7, 7)"
)
_CATALOG = {
    "columns": "SELECT column_name, data_type, character_maximum_length, numeric_precision, numeric_scale, "
    "is_nullable, column_default FROM information_schema.columns WHERE table_schema = current_schema()",
    "constraints": "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE connamespace = current_schema()::regnamespace",
    "indexes": "SELECT indexname, replace(indexdef, schemaname || '.', '') FROM pg_indexes "
    "WHERE schemaname = current_schema()",
}


def run_migration(engine, step: str, path: Path = _PATH) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@contextmanager
def throwaway_schema(build):
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"ads_contrib_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        build(eng)
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture()
def engine():
    with throwaway_schema(lambda eng: run_migration(eng, "upgrade")) as eng:
        yield eng


def _catalog(engine) -> dict[str, set[tuple]]:
    with engine.connect() as conn:
        return {kind: {tuple(r) for r in conn.execute(text(sql))} for kind, sql in _CATALOG.items()}


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    assert isinstance(script.get_revision(REVISION).down_revision, str)
    [head] = script.get_heads()
    assert REVISION in {r.revision for r in script.walk_revisions(base="base", head=head)}


@pytest.mark.postgres
def test_migrated_schema_matches_the_orm_and_downgrade_drops_it(engine) -> None:
    from tests.services.ml_ads.conftest import restore_pg_types

    restore_pg_types()
    with throwaway_schema(lambda eng: Base.metadata.tables[TABLE].create(bind=eng)) as orm:
        declared = _catalog(orm)
    migrated = _catalog(engine)
    for kind in _CATALOG:
        assert migrated[kind] == declared[kind], kind
    assert ("ix_ml_ads_campaign_contributions_campaign",) == tuple(
        n for n, _ in migrated["indexes"] if n.startswith("ix_")
    )
    run_migration(engine, "downgrade")
    with engine.connect() as conn:
        assert conn.execute(text(f"SELECT to_regclass('{TABLE}')")).scalar_one() is None


@pytest.mark.postgres
@pytest.mark.parametrize(
    "row",
    [
        {"kind": "percentage", "value": "0"},
        {"kind": "percentage", "value": "100.01"},
        {"kind": "fixed_amount", "value": "0"},
        {"kind": "bonus", "value": "10"},
        {"kind": "percentage", "value": "10", "desde": "2026-11-01"},  # starts after it ends
    ],
)
def test_the_database_rejects_out_of_bounds_rows(engine, row) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text(_INSERT), {"desde": "2026-10-01", "hasta": "2026-10-31", **row})

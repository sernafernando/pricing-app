"""The reactivation queue migration creates what the model maps, and downgrades cleanly (Postgres only)."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261018_promo_refresh_reactivation.py"


def test_upgrade_matches_the_model_and_downgrade_drops_it() -> None:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    from app.models.promo_refresh_reactivation import PromoRefreshReactivation

    spec = importlib.util.spec_from_file_location("promo_reactivation_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"promo_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                migration.upgrade()
                inspector = inspect(conn)
                columns = {c["name"] for c in inspector.get_columns("promo_refresh_reactivation")}
                assert columns == {c.name for c in PromoRefreshReactivation.__table__.columns}
                assert {u["name"] for u in inspector.get_unique_constraints("promo_refresh_reactivation")} == {
                    "uq_promo_refresh_reactivation_mla"
                }
                migration.downgrade()
                assert "promo_refresh_reactivation" not in inspect(conn).get_table_names()
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()

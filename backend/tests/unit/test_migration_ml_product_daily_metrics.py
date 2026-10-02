"""ODD `metricas-ml-tablero` T2: migration `20261001_ml_product_daily_metrics`.
Graph layer always; a Postgres round trip proves the DDL matches the model
(every column the ORM writes exists, the upsert key is unique)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261001_ml_product_daily_metrics"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_product_daily_metrics_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_single_head_contains_the_revision() -> None:
    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


@pytest.mark.postgres
def test_round_trip_matches_the_model(pg_engine) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.models.ml_daily_metrics import MlProductDailyMetrics

    migration = _load_migration()
    with pg_engine.connect() as conn:
        if sa.inspect(conn).has_table(migration.TABLE):
            pytest.skip("table already exists in the shared test DB")
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
            inspector = sa.inspect(conn)
            columns = {c["name"] for c in inspector.get_columns(migration.TABLE)}
            uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints(migration.TABLE)}
            migration.downgrade()
        conn.commit()
        assert not sa.inspect(conn).has_table(migration.TABLE)

    assert columns == {c.name for c in MlProductDailyMetrics.__table__.columns}
    assert ("product_item_id", "mla", "day") in uniques

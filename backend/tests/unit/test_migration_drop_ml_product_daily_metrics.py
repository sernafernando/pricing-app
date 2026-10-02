"""ODD `metricas-ml-tablero`, "Sin tabla resumen" ST4: the daily rollup is
gone. The board reads the orders; nothing writes or reads
`ml_product_daily_metrics` any more, and a migration on the single alembic
line drops the table (its indexes go with it)."""

from __future__ import annotations

import importlib.util
import os

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261002_drop_ml_product_daily_metrics"
_TABLE = "ml_product_daily_metrics"


def _script() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_drop_is_on_the_single_alembic_line() -> None:
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


@pytest.mark.parametrize(
    "module",
    [
        "app.models.ml_daily_metrics",
        "app.services.ml_daily_metrics.rollup",
        "app.scripts.backfill_ml_daily_metrics",
    ],
)
def test_the_rollup_code_is_gone(module: str) -> None:
    assert importlib.util.find_spec(module) is None


def test_no_model_maps_the_table() -> None:
    from app.core.database import Base

    assert _TABLE not in Base.metadata.tables


def test_storing_order_metrics_never_mentions_the_rollup() -> None:
    from app.services.order_metrics import store

    source = open(store.__file__, encoding="utf-8").read()
    assert "rollup" not in source and "ml_daily_metrics" not in source


@pytest.mark.postgres
def test_round_trip_drops_and_restores_the_table(pg_engine) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    script = _script()
    create = script.get_revision("20261001_ml_product_daily_metrics").module
    drop = script.get_revision(_REVISION).module
    with pg_engine.connect() as conn:
        if sa.inspect(conn).has_table(_TABLE):
            pytest.skip("table already exists in the shared test DB")
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            create.upgrade()
            conn.execute(sa.text(f"CREATE INDEX ix_ml_product_daily_metrics_updated_at ON {_TABLE} (updated_at)"))
            drop.upgrade()
            dropped = not sa.inspect(conn).has_table(_TABLE)
            drop.upgrade()  # idempotent: a database that never had it
            drop.downgrade()
            restored = sa.inspect(conn).has_table(_TABLE)
            indexes = {ix["name"] for ix in sa.inspect(conn).get_indexes(_TABLE)}
            create.downgrade()
            conn.execute(sa.text("DROP INDEX IF EXISTS ix_ml_product_daily_metrics_updated_at"))
        conn.commit()

    assert dropped and restored
    assert {"ix_ml_product_daily_metrics_day", "ix_ml_product_daily_metrics_mla_day"} <= indexes

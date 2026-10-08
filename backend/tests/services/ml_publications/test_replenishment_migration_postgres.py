"""Migration `20261011_ml_user_product_replenishment`: new state table, additive and reversible.

Runs inside a throwaway schema of the Postgres test DB. The model must match the table the migration
creates, column for column, so the P4b writer can rely on either.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_REVISION = "20261011_ml_user_product_replenishment"
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / f"{_REVISION}.py"
_TABLE = "ml_user_product_replenishment"

TYPED_COLUMNS = {
    "partial",
    "content_missing",
    "period",
    "units_30d",
    "gmv_30d",
    "currency_id",
    "units_7d",
    "units_14d",
    "units_21d",
    "days_out_of_stock_21d",
    "history_through",
    "total_stock",
    "shipping_urgency",
    "minimum_distributable_stock",
}
STATE_COLUMNS = {
    "raw",
    "raw_hash",
    "http_status",
    "error_body",
    "last_error",
    "first_seen_at",
    "fetched_at",
    "fetched_request_started_at",
    "never_existed",
    "last_checked_at",
    "gone_at",
}


def _script() -> ScriptDirectory:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_revision_is_in_a_single_head_chain() -> None:
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {rev.revision for rev in script.walk_revisions(base="base", head=heads[0])}


def test_the_model_declares_the_state_and_typed_columns() -> None:
    from app.models.ml_publications import MlUserProductReplenishment

    columns = {c.name: c for c in MlUserProductReplenishment.__table__.columns}
    assert MlUserProductReplenishment.__tablename__ == _TABLE
    assert set(columns) == {"user_product_id"} | TYPED_COLUMNS | STATE_COLUMNS
    assert columns["user_product_id"].primary_key
    assert columns["gmv_30d"].type.precision == 16 and columns["gmv_30d"].type.scale == 2


def test_the_model_is_registered_with_the_store_by_the_fetcher_pr() -> None:
    """P4a left the model unregistered; the fetcher PR (P4b) registers it. Fetching stays off until the
    operator lists `replenishment` in `bundle_resources` (see test_replenishment_wiring)."""
    from app.models.ml_publications import MlUserProductReplenishment
    from app.services.ml_publications.resources import RESOURCES
    from app.services.ml_publications.subresource_store import MODELS

    assert MODELS["replenishment"] is MlUserProductReplenishment
    assert "replenishment" in RESOURCES


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"repl_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def _run(engine, step: str) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    spec = importlib.util.spec_from_file_location("ml_user_product_replenishment_migration", _MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(migration, step)()


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_creates_the_table_matching_the_model(engine) -> None:
    from app.models.ml_publications import MlUserProductReplenishment

    _run(engine, "upgrade")
    assert _table_exists(engine)
    db_columns = {c["name"]: c for c in inspect(engine).get_columns(_TABLE)}
    model_columns = {c.name: c for c in MlUserProductReplenishment.__table__.columns}
    assert set(db_columns) == set(model_columns)
    for name, column in model_columns.items():
        assert db_columns[name]["nullable"] == column.nullable or column.primary_key, name
    assert inspect(engine).get_pk_constraint(_TABLE)["constrained_columns"] == ["user_product_id"]


def _table_exists(engine) -> bool:
    return _TABLE in _tables(engine)


def test_state_defaults_match_the_other_sub_resource_tables(engine) -> None:
    _run(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {_TABLE} (user_product_id) VALUES ('MLAU1')"))
        row = conn.execute(text(f"SELECT never_existed, first_seen_at, partial FROM {_TABLE}")).one()
    assert row.never_existed is False
    assert row.first_seen_at is not None
    assert row.partial is None  # unknown until a body is mapped


def test_downgrade_drops_the_table_and_leaves_the_rest(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE ml_user_product_stock (user_product_id text PRIMARY KEY)"))
    _run(engine, "upgrade")
    _run(engine, "downgrade")
    assert not _table_exists(engine)
    assert "ml_user_product_stock" in _tables(engine)


def test_upgrade_downgrade_upgrade_is_repeatable(engine) -> None:
    _run(engine, "upgrade")
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    assert _table_exists(engine)

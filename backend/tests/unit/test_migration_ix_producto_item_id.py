"""PFILT R43: `ml_order_item_costos.producto_item_id` gets its own index.

Every product facet on the Ventas ML screen (marca, subcategoría, PM)
crosses that column, the listing pages up to 200 rows and the KPI
aggregates the whole filtered set. The index ships in its own migration,
deployed BEFORE the PR that adds those joins.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260922_ix_producto_item_id"
_INDEX = "ix_ml_order_item_costos_producto_item_id"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_revision_exists_and_has_one_parent() -> None:
    script = _script_directory()
    revision = script.get_revision(_REVISION)
    assert revision is not None
    # Parent not pinned by name: a rebase onto a main that added migrations
    # legitimately moves it. What must hold is a single linear parent.
    assert isinstance(revision.down_revision, str)
    assert script.get_revision(revision.down_revision) is not None


def test_the_graph_has_a_single_head_containing_this_revision() -> None:
    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_the_model_declares_the_index() -> None:
    from app.models.ml_order_item_costo import MlOrderItemCosto

    indexes = {ix.name for ix in MlOrderItemCosto.__table__.indexes}
    assert _INDEX in indexes, "the ORM schema (create_all in tests) must match the migration"


@pytest.mark.postgres
def test_upgrade_creates_the_index_and_downgrade_removes_it(pg_order_metrics_engine) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ix_producto_item_id_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    with pg_order_metrics_engine.connect() as conn:
        pre_existing = _INDEX in {ix["name"] for ix in sa.inspect(conn).get_indexes("ml_order_item_costos")}
        ctx = MigrationContext.configure(conn)
        op_obj = Operations(ctx)
        op_obj._install_proxy()
        try:
            migration.upgrade()
            conn.commit()
            assert _INDEX in {ix["name"] for ix in sa.inspect(conn).get_indexes("ml_order_item_costos")}

            migration.downgrade()
            conn.commit()
            assert _INDEX not in {ix["name"] for ix in sa.inspect(conn).get_indexes("ml_order_item_costos")}
        finally:
            op_obj._remove_proxy()
            if pre_existing:
                # Restore exactly the state found: never leave a shared test
                # schema worse than it was.
                conn.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON ml_order_item_costos (producto_item_id)"))
                conn.commit()

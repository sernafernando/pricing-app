"""ml-billing-balance PR 4a-i -- migration `20261013_ml_billing_sweep_gaps`.

Graph layer: single head, and this revision is reachable from it (the head is
never pinned: a rebase onto a main that added migrations moves it).

Model layer: the gaps table has the columns the design lists and ONE row per
(period, document type, source, paging, position).

Round trip (`@pytest.mark.postgres`): upgrade creates the table with its
unique constraint, downgrade drops it.
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
_REVISION = "20261013_ml_billing_sweep_gaps"
_TABLE = "ml_billing_sweep_gaps"

_COLUMNS = {
    "id",
    "period_key",
    "document_type",
    "billing_source",
    "paging",
    "position",
    "window",
    "http_status",
    "error",
    "first_seen_at",
    "last_seen_at",
    "seen_count",
    "resolved_at",
    "lap_id",
}
_UNIQUE_KEY = ("period_key", "document_type", "billing_source", "paging", "position")


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_billing_sweep_gaps_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
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


class TestModel:
    def test_columns_match_the_design(self) -> None:
        from app.models.ml_billing import MlBillingSweepGap

        assert set(MlBillingSweepGap.__table__.columns.keys()) == _COLUMNS

    def test_position_is_unique_per_period_type_source_and_paging(self) -> None:
        from app.models.ml_billing import MlBillingSweepGap

        uniques = [
            tuple(c.name for c in constraint.columns)
            for constraint in MlBillingSweepGap.__table__.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        ]
        assert _UNIQUE_KEY in uniques

    def test_no_cached_completeness_is_stored_on_a_gap(self) -> None:
        from app.models.ml_billing import MlBillingSweepGap

        assert {"complete", "stored_count", "stored_sum"}.isdisjoint(MlBillingSweepGap.__table__.columns.keys())


@pytest.mark.postgres
class TestMigrationPostgresRoundTrip:
    def test_upgrade_creates_the_table_and_downgrade_drops_it(self, pg_engine) -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        migration = _load_migration()
        with pg_engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {_TABLE}"))

        try:
            with pg_engine.connect() as conn:
                op_obj = Operations(MigrationContext.configure(conn))
                op_obj._install_proxy()
                try:
                    migration.upgrade()
                    conn.commit()

                    inspector = sa.inspect(conn)
                    assert _TABLE in inspector.get_table_names()
                    assert {c["name"] for c in inspector.get_columns(_TABLE)} == _COLUMNS
                    uniques = [tuple(u["column_names"]) for u in inspector.get_unique_constraints(_TABLE)]
                    assert _UNIQUE_KEY in uniques

                    migration.downgrade()
                    conn.commit()

                    assert _TABLE not in sa.inspect(conn).get_table_names()
                finally:
                    op_obj._remove_proxy()
        finally:
            with pg_engine.begin() as conn:
                conn.execute(sa.text(f"DROP TABLE IF EXISTS {_TABLE}"))

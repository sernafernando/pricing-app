"""Migration `20261009_om_dirty_priority_index`: graph + DDL."""

from __future__ import annotations

import os

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261009_om_dirty_priority_index"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


class TestMigrationGraph:
    def test_single_head_that_contains_this_revision(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain, f"{_REVISION!r} is not an ancestor of the single head {heads[0]!r}"

    def test_has_exactly_one_parent(self) -> None:
        revision = _script_directory().get_revision(_REVISION)
        assert isinstance(revision.down_revision, str)


class TestMigrationShape:
    def test_builds_the_index_concurrently_with_a_lock_timeout(self) -> None:
        path = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
        source = open(path, encoding="utf-8").read()
        assert "CREATE INDEX CONCURRENTLY" in source
        assert "autocommit_block" in source
        assert "lock_timeout" in source

    def test_index_expression_matches_the_claim_order_by(self) -> None:
        from app.services.order_metrics import queue

        path = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
        source = open(path, encoding="utf-8").read()
        assert "((reason IN ('divergence', 'reconcile')), enqueued_at)" in source
        assert queue._TIER_SQL == "(reason IN ('divergence', 'reconcile'))"

    def test_model_index_expression_matches_the_claim_order_by(self) -> None:
        from app.models.ml_order_metrics import MlOrderMetricsDirty
        from app.services.order_metrics import queue

        index = next(i for i in MlOrderMetricsDirty.__table__.indexes if i.name == "ix_ml_order_metrics_dirty_priority")
        assert str(index.expressions[0]) == queue._TIER_SQL


@pytest.mark.postgres
class TestMigrationDdl:
    def test_upgrade_creates_and_downgrade_drops_the_index(self, pg_order_metrics_engine) -> None:
        import importlib.util

        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        path = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
        spec = importlib.util.spec_from_file_location("om_dirty_priority_index_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def _exists(conn) -> bool:
            return bool(
                conn.exec_driver_sql("SELECT 1 FROM pg_indexes WHERE indexname = %s", (module._INDEX,)).fetchone()
            )

        def _valid(conn) -> bool:
            return bool(
                conn.exec_driver_sql(
                    "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = %s",
                    (module._INDEX,),
                ).scalar()
            )

        with pg_order_metrics_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.downgrade()
                assert not _exists(conn)
                module.upgrade()
                assert _exists(conn)
                module.upgrade()  # idempotent
                assert _exists(conn)

                # A build that died midway leaves the index INVALID: upgrade must rebuild it.
                conn.exec_driver_sql(
                    "UPDATE pg_index SET indisvalid = false "
                    "WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = %s)",
                    (module._INDEX,),
                )
                assert not _valid(conn)
                module.upgrade()
                assert _exists(conn)
                assert _valid(conn)

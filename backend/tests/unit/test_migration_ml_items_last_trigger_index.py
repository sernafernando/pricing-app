"""Migration `20261011_ml_items_last_trigger_index`: graph, shape and DDL (P5.T6).

The index serves the default order of the Publicaciones list (recent activity, nulls last, closed by
`item_id`) over live items, so the first page is an index walk instead of a sort of the whole table.
"""

from __future__ import annotations

import importlib.util
import os

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261011_ml_items_last_trigger_index"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_DEFAULT_ORDER = (
    "SELECT item_id FROM ml_items WHERE gone_at IS NULL "
    "ORDER BY last_trigger_received_at DESC NULLS LAST, item_id LIMIT 50"
)


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _source() -> str:
    with open(_PATH, encoding="utf-8") as handle:
        return handle.read()


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
    def test_builds_the_index_concurrently_with_a_lock_timeout_and_cleans_an_invalid_leftover(self) -> None:
        source = _source()
        assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in source
        assert "autocommit_block" in source
        assert "lock_timeout" in source and "RESET lock_timeout" in source
        assert "indisvalid" in source and "DROP INDEX CONCURRENTLY IF EXISTS" in source

    def test_the_index_is_the_default_order_of_the_list_over_live_items(self) -> None:
        source = _source()
        assert "(last_trigger_received_at DESC NULLS LAST, item_id)" in source
        assert "WHERE gone_at IS NULL" in source


class TestModelMirror:
    """Alembic autogenerate compares the model with the database: an index only in the migration would be
    proposed for DROP. The model declares it for Postgres only (`NULLS LAST` is not valid SQLite DDL, and the
    unit tests build their schema from this metadata on SQLite: every SQLite-backed test would fail if the index
    were emitted there)."""

    def test_the_model_declares_the_index_like_the_migration(self) -> None:
        from app.models.ml_publications import MlItem

        index = next(i for i in MlItem.__table__.indexes if i.name == "ix_ml_items_last_trigger")
        assert [str(e) for e in index.expressions] == ["last_trigger_received_at DESC NULLS LAST", "ml_items.item_id"]
        assert str(index.dialect_options["postgresql"]["where"]) == "gone_at IS NULL"


def _migration():
    spec = importlib.util.spec_from_file_location("ml_items_last_trigger_index_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.postgres
class TestMigrationDdl:
    @staticmethod
    def _exists(conn, name: str) -> bool:
        return bool(
            conn.exec_driver_sql(
                "SELECT 1 FROM pg_indexes WHERE indexname = %s AND schemaname = current_schema()", (name,)
            ).fetchone()
        )

    @staticmethod
    def _valid(conn, name: str) -> bool:
        return bool(
            conn.exec_driver_sql(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = %s AND n.nspname = current_schema()",
                (name,),
            ).scalar()
        )

    def test_upgrade_creates_a_valid_index_and_downgrade_drops_it(self, mlpub_pg) -> None:  # noqa: F811
        module = _migration()
        with mlpub_pg.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.downgrade()
                assert not self._exists(conn, module._INDEX)
                module.upgrade()
                assert self._exists(conn, module._INDEX) and self._valid(conn, module._INDEX)
                module.upgrade()  # idempotent
                assert self._valid(conn, module._INDEX)
                module.downgrade()
                assert not self._exists(conn, module._INDEX)

    def test_an_invalid_leftover_of_a_failed_build_is_rebuilt(self, mlpub_pg) -> None:  # noqa: F811
        module = _migration()
        with mlpub_pg.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.upgrade()
                conn.exec_driver_sql(
                    "UPDATE pg_index SET indisvalid = false "
                    "WHERE indexrelid = (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relname = %s AND n.nspname = current_schema())",
                    (module._INDEX,),
                )
                assert not self._valid(conn, module._INDEX)
                module.upgrade()
                assert self._valid(conn, module._INDEX)

    def test_the_planner_can_walk_the_index_for_the_default_order(self, mlpub_pg) -> None:  # noqa: F811
        module = _migration()
        with mlpub_pg.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.upgrade()
                conn.exec_driver_sql("SET enable_seqscan = off")
                try:
                    plan = "\n".join(r[0] for r in conn.execute(text("EXPLAIN " + _DEFAULT_ORDER)))
                finally:
                    conn.exec_driver_sql("RESET enable_seqscan")
        assert module._INDEX in plan and "Sort" not in plan, plan

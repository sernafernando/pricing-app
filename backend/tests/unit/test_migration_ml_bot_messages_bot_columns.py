"""
Phase A (PR1), T1.1 — migration `20260722_ml_bot_messages_bot_columns`.

Mirrors `test_ml_bot_answer_history_migration.py`'s dialect-agnostic
revision-graph layer (runs on SQLite CI): confirms the migration is a
single-head continuation of the chain and that `upgrade()`/`downgrade()`
import cleanly + are dialect-guarded (partial index only on Postgres).
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260722_ml_bot_messages_bot_columns"
_DOWN_REVISION = "compras_037_pedido_cuenta_corriente"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
        script = _script_directory()
        revision = script.get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == _DOWN_REVISION

    def test_is_current_head(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert _REVISION in heads


class TestMigrationSqliteDialectGuard:
    """SQLite round-trip using the module's own `upgrade`/`downgrade`
    against a minimal table shape (mirrors ml_bot_messages' real columns
    closely enough to prove the ADD COLUMN + index DDL is dialect-safe)."""

    def _make_engine(self) -> sa.Engine:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with engine.begin() as conn:
            conn.execute(
                sa.text("CREATE TABLE ml_bot_messages (id INTEGER PRIMARY KEY, ml_message_id VARCHAR(64) NOT NULL)")
            )
        return engine

    def _load_migration(self):
        import importlib.util
        from pathlib import Path

        path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
        spec = importlib.util.spec_from_file_location("ml_bot_messages_bot_columns_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_upgrade_then_downgrade_round_trip_on_sqlite(self) -> None:
        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        engine = self._make_engine()
        migration = self._load_migration()

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op_obj = Operations(ctx)

            op_obj._install_proxy()
            try:
                migration.upgrade()
                inspector = sa.inspect(conn)
                columns = {col["name"] for col in inspector.get_columns("ml_bot_messages")}
                assert "bot_status" in columns
                assert "drafted_answer" in columns
                assert "intent_category" in columns
                assert "confidence" in columns
                assert "answer_source" in columns
                assert "llm_provider" in columns
                assert "attempts" in columns
                assert "last_error" in columns
                assert "drafted_at" in columns
                assert "bot_updated_at" in columns

                index_names = {idx["name"] for idx in inspector.get_indexes("ml_bot_messages")}
                assert "idx_ml_bot_messages_bot_status" in index_names

                migration.downgrade()
                columns_after = {col["name"] for col in sa.inspect(conn).get_columns("ml_bot_messages")}
                assert "bot_status" not in columns_after
            finally:
                op_obj._remove_proxy()

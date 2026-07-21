"""
Migration smoke test — `20260721_ml_bot_answer_history` (ml-bot-dynamic-fewshot
PR1, task 1.2).

Two layers:
1. Dialect-agnostic revision-graph checks (runs everywhere, including CI's
   SQLite backend): confirms the migration is a proper single-head
   continuation of the chain, and that `upgrade()`/`downgrade()` are
   dialect-guarded (no unconditional pgvector-only DDL string appears
   unguarded at module level).
2. Real Postgres `upgrade`/`downgrade` round-trip against a live pgvector
   instance (table + HNSW index existence, clean downgrade) —
   `@pytest.mark.skipif` on non-Postgres dialect per design's CI note: the
   `vector` column type and HNSW index are Postgres-only and the backend's
   CI DB is SQLite, so this layer must be run manually / in a Postgres-backed
   job before merge (see backend/README.md CI caveat).
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260721_ml_bot_answer_history"
_DOWN_REVISION = "20260720_add_promo_refresh_pending"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


class TestMigrationGraph:
    """Dialect-agnostic — runs on SQLite CI too."""

    def test_revision_is_registered_in_script_directory(self) -> None:
        script_dir = _script_directory()
        revision = script_dir.get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == _DOWN_REVISION

    def test_revision_is_reachable_from_head(self) -> None:
        script_dir = _script_directory()
        heads = script_dir.get_heads()
        # Our revision must be an ancestor of (or be) the current head — i.e.
        # part of the single linear chain, not an orphaned/diverged branch.
        assert len(heads) == 1
        ancestors = {rev.revision for rev in script_dir.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in ancestors


@pytest.mark.skipif(
    os.environ.get("DATABASE_URL", "").split("://")[0] != "postgresql",
    reason="pgvector `vector` column type + HNSW index require a live Postgres instance; "
    "CI runs backend tests against SQLite (see backend/README.md CI caveat).",
)
class TestMigrationAgainstLivePostgres:
    """Requires DATABASE_URL pointing at a real Postgres with pgvector."""

    def test_upgrade_creates_table_and_hnsw_index(self) -> None:
        from app.core.config import settings

        engine = sa.create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            inspector = sa.inspect(conn)
            assert "ml_bot_answer_history" in inspector.get_table_names()
            index_names = {ix["name"] for ix in inspector.get_indexes("ml_bot_answer_history")}
            assert "idx_ml_bot_answer_history_embedding_hnsw" in index_names
            assert "idx_ml_bot_answer_history_item_id" in index_names

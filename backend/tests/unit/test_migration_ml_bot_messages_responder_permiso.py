"""
Phase A (PR2) — migration `20260722_ml_bot_messages_responder_permiso`.

Mirrors `test_migration_ml_bot_messages_bot_columns.py`'s dialect-agnostic
revision-graph layer (runs on SQLite CI): confirms the migration is the
current single head of the chain and correctly chained on top of PR1's
migration.
"""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260722_ml_bot_messages_responder_permiso"
_DOWN_REVISION = "20260722_ml_bot_messages_bot_columns"


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
        assert list(heads) == [_REVISION]

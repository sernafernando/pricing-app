"""
tn-reconcile-publish Slice 1 — migration `20260722_tn_reconcile_tables`.

Mirrors `test_migration_ml_bot_messages_bot_columns.py`'s dialect-agnostic
revision-graph layer (runs on SQLite CI): confirms the migration is
registered and correctly chained on top of the prior head. It is no longer
the chain's current head — `20260722_tn_producto_published` (DESPUBLICAR
bugfix) was chained on top of it afterwards.
"""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260722_tn_reconcile_tables"
_DOWN_REVISION = "20260722_ml_bot_messages_responder_permiso"


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

    def test_is_ancestor_of_current_head(self) -> None:
        script = _script_directory()
        (head,) = script.get_heads()
        ancestor_revisions = {rev.revision for rev in script.walk_revisions(base="base", head=head)}
        assert _REVISION in ancestor_revisions

"""
DESPUBLICAR bugfix — migration `20260722_tn_producto_published`.

Adds nullable `published` column to `tienda_nube_productos`. Confirms the
migration is registered, correctly chained on top of the Slice 1 tables
migration, and is an ancestor of the current head.

Round 6, item 2: this file used to assert `test_is_current_head` (hard-coding
that this exact revision IS the chain's tip). That assertion had already
broken twice elsewhere in this same PR (`test_migration_ml_bot_messages_responder_permiso.py`,
`test_migration_tn_reconcile_tables.py`) every time a later migration chained
on top, and then got planted again here. Copied the same
`test_is_ancestor_of_current_head` pattern those files use instead — the
next migration anyone adds on top of this one no longer breaks this test.
"""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260722_tn_producto_published"
_DOWN_REVISION = "20260722_tn_reconcile_tables"


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

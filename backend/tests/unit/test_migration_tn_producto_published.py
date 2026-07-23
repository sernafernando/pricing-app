"""
DESPUBLICAR bugfix — migration `20260722_tn_producto_published`.

Adds nullable `published` column to `tienda_nube_productos`. Confirms the
migration is registered, correctly chained on top of the Slice 1 tables
migration, and is currently the single head of the chain.
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

    def test_is_current_head(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert list(heads) == [_REVISION]

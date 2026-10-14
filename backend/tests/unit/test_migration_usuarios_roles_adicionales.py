"""Migration `20261022_usuarios_roles_adicionales`: registered, chained on the head it was
written against, and an ancestor of the current head (never asserts it IS the head, so
the next migration on top does not break this test)."""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261022_usuarios_roles_adicionales"
_DOWN_REVISION = "20261021_ml_pub_queue_unpark_items"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_revision_is_registered_and_linked() -> None:
    revision = _script_directory().get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == _DOWN_REVISION


def test_is_ancestor_of_current_head() -> None:
    script = _script_directory()
    (head,) = script.get_heads()
    assert _REVISION in {rev.revision for rev in script.walk_revisions(base="base", head=head)}

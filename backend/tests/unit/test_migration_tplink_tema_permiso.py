"""
Migration `20261026_tplink_tema_permiso`: the `tplink.tema` permission, which only
turns on the TP-Link theme (no data lock). Revision-graph checks plus a static
look at the SQL; the upgrade/downgrade round trip runs against a scratch
Postgres outside the suite.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261026_tplink_tema_permiso"
_DOWN_REVISION = "20261025_tp_cost_columns"
_FILE = Path(_BACKEND_ROOT) / "alembic" / "versions" / "20261026_tplink_tema_permiso.py"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _bodies() -> tuple[str, str]:
    text = _FILE.read_text(encoding="utf-8")
    upgrade = text.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    downgrade = text.split("def downgrade()", 1)[1]
    return upgrade, downgrade


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
        revision = _script_directory().get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == _DOWN_REVISION

    def test_is_ancestor_of_current_head(self) -> None:
        script = _script_directory()
        (head,) = script.get_heads()
        assert _REVISION in {rev.revision for rev in script.walk_revisions(base="base", head=head)}


class TestMigrationSql:
    def test_upgrade_inserts_the_permission_idempotently(self) -> None:
        upgrade, _ = _bodies()
        assert "INSERT INTO permisos" in upgrade
        assert "'tplink.tema'" in upgrade
        assert "'ventas_ml'" in upgrade
        assert "ON CONFLICT (codigo) DO NOTHING" in upgrade

    def test_upgrade_grants_it_to_no_role(self) -> None:
        upgrade, _ = _bodies()
        assert "roles_permisos_base" not in upgrade
        assert "usuarios_permisos_override" not in upgrade

    def test_downgrade_removes_grants_then_the_permission(self) -> None:
        _, downgrade = _bodies()
        roles = downgrade.index("DELETE FROM roles_permisos_base")
        overrides = downgrade.index("DELETE FROM usuarios_permisos_override")
        permiso = downgrade.index("DELETE FROM permisos WHERE codigo = 'tplink.tema'")
        assert roles < permiso and overrides < permiso

"""The `ml_ops.resincronizar` permission migration (ODD
`ventas-ml-ui-pendiente` T7): one alembic head, same registration shape as
`ml_ops.varios_editar`, ADMIN only."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "20260930_ml_ops_resincronizar_perm.py"


def _module():
    spec = importlib.util.spec_from_file_location("mig_ml_ops_resincronizar", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_there_is_a_single_alembic_head_and_it_contains_this_migration():
    # Not pinned to the head by name: every later migration would break it.
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == "20260930_ml_ops_resincronizar" for rev in script.walk_revisions("base", heads[0]))


def test_registers_the_permission_for_admin_only():
    module = _module()
    assert module.CODIGO == "ml_ops.resincronizar"
    assert module.PERMISO_CATEGORIA == "ml_ops"
    assert module.ROL_PERMISOS == {"ADMIN": ["ml_ops.resincronizar"]}
    assert module.down_revision == "20260929_ml_group_metrics_gross_amount"

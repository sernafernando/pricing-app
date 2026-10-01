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


def test_there_is_a_single_alembic_head_and_it_is_this_migration():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert heads == ["20260930_ml_ops_resincronizar"]


def test_registers_the_permission_for_admin_only():
    module = _module()
    assert module.CODIGO == "ml_ops.resincronizar"
    assert module.PERMISO_CATEGORIA == "ml_ops"
    assert module.ROL_PERMISOS == {"ADMIN": ["ml_ops.resincronizar"]}
    assert module.down_revision == "20260929_ml_group_metrics_gross_amount"

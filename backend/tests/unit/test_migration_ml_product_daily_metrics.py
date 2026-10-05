"""ODD `metricas-ml-tablero` T2: migration `20261001_ml_product_daily_metrics`
stays on the single alembic line (history). Since "Sin tabla resumen" no code
maps or writes the table; `20261005_drop_ml_product_daily_metrics` drops it
(`tests/unit/test_rollup_removed.py`)."""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261001_ml_product_daily_metrics"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_single_head_contains_the_revision() -> None:
    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))

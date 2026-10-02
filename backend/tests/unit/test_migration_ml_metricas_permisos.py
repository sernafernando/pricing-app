"""ODD `metricas-ml-tablero` T3: the board's permission pair ships in its own
migration on the single alembic line, and the codes match what the router
checks."""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.routers import ml_metricas

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261001_ml_metricas_permisos"


def _script() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_single_head_contains_the_revision() -> None:
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_codes_match_the_router_and_reach_admin_and_gerente() -> None:
    module = _script().get_revision(_REVISION).module
    codes = {codigo for codigo, *_rest in module.PERMISOS}
    assert codes == {ml_metricas.PERMISO_VER, ml_metricas.PERMISO_GANANCIA}
    assert set(module.ROL_PERMISOS["ADMIN"]) == codes
    assert set(module.ROL_PERMISOS["GERENTE"]) == codes


def test_board_read_indexes_ship_in_a_migration_and_match_the_models() -> None:
    from app.models.ml_group_metrics import MlGroupMetrics

    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    module = script.get_revision("20261001_ix_board_reads").module
    declared = {ix.name for ix in MlGroupMetrics.__table__.indexes}
    # The rollup's index stays in the database with its (now unused) table
    # until the follow-up drop; no model declares it any more.
    assert set(module.INDEXES) - {"ix_ml_product_daily_metrics_updated_at"} <= declared

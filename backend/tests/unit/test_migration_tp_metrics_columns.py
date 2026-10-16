"""Migration `20261027_tp_metrics_columns` (metricas-ml-tplink-mode P3).

Graph and frozen-copy assertions run everywhere; the real upgrade/downgrade
round trip against Postgres is `test_migration_tp_metrics_columns_postgres.py`.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_sale_line import MlSaleLine
from app.services.order_metrics import triggers

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261027_tp_metrics_columns"
_PARENT = "20261026_tplink_tema_permiso"
_TRIGGERS_REVISION = "20260923_ml_order_metrics_triggers_orders"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load(revision: str) -> ModuleType:
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_is_on_the_current_head_line_on_top_of_the_theme_permission(self) -> None:
        script = _script_directory()
        (head,) = script.get_heads()
        assert _REVISION in {rev.revision for rev in script.walk_revisions(base="base", head=head)}
        assert script.get_revision(_REVISION).down_revision == _PARENT


class TestColumns:
    def test_adds_exactly_the_nullable_tp_columns_of_the_models(self) -> None:
        migration = _load(_REVISION)
        for model, columns in ((MlOrderMetrics, migration._METRICS_COLUMNS), (MlSaleLine, migration._LINES_COLUMNS)):
            names = [column.name for column in columns]
            assert all(column.nullable for column in columns)
            assert all(model.__table__.c[name].nullable for name in names)
            assert {c for c in model.__table__.c.keys() if "tp" in c} == set(names)


class TestFrozenTriggerCopy:
    def test_upgrade_installs_the_live_trigger_definition(self) -> None:
        sql = _load(_REVISION)._UPDATE_TRIGGER_SQL
        assert "costo_tp_unitario_ars" in sql
        assert sql.strip() in triggers._ORDER_ITEM_COSTOS_TRIGGER_SQL

    def test_downgrade_restores_the_trigger_the_original_migration_created(self) -> None:
        previous = _load(_REVISION)._PREVIOUS_UPDATE_TRIGGER_SQL
        assert "costo_tp" not in previous
        assert previous.strip() in _load(_TRIGGERS_REVISION)._ORDER_ITEM_COSTOS_TRIGGER_SQL

    def test_upgrade_installs_the_live_enqueue_functions(self) -> None:
        migration = _load(_REVISION)
        assert migration._ENQUEUE_TP_COST_FUNCTION_SQL.strip() in triggers._ENQUEUE_TP_COST_FUNCTION_SQL
        assert migration._ITEM_COSTOS_FUNCTION_SQL.strip() in triggers._ORDER_ITEM_COSTOS_TRIGGER_SQL

    def test_downgrade_restores_the_original_item_costos_function(self) -> None:
        body = _load(_REVISION)._PREVIOUS_ITEM_COSTOS_FUNCTION_BODY
        assert "order_metrics_enqueue_tp_cost" not in body
        assert body.strip() in _load(_TRIGGERS_REVISION)._ORDER_ITEM_COSTOS_TRIGGER_SQL

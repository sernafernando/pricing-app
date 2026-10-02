"""ODD `metricas-ml-tablero`, "Sin tabla resumen" ST4: the daily rollup's
code is gone -- the board reads the orders and nothing writes or reads
`ml_product_daily_metrics` any more.

Two-phase removal: THIS release removes the code only and leaves the table in
place, unused. The migration that drops it ships in a follow-up PR, after
this one is deployed: run during the deploy, before the workers restart, a
drop would make every metrics store of the still-running old workers fail
(they refresh the rollup in the same transaction) until they restart.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import pathlib

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TABLE = "ml_product_daily_metrics"


def _script() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


@pytest.mark.parametrize(
    "module",
    [
        "app.models.ml_daily_metrics",
        "app.services.ml_daily_metrics.rollup",
        "app.scripts.backfill_ml_daily_metrics",
    ],
)
def test_the_rollup_code_is_gone(module: str) -> None:
    assert importlib.util.find_spec(module) is None


def test_no_model_maps_the_table() -> None:
    from app.core.database import Base

    assert _TABLE not in Base.metadata.tables


def test_storing_order_metrics_never_mentions_the_rollup() -> None:
    from app.services.order_metrics import store

    source = pathlib.Path(store.__file__).read_text(encoding="utf-8")
    assert "rollup" not in source and "ml_daily_metrics" not in source


def test_no_migration_of_this_release_drops_the_table() -> None:
    """The DROP waits for the follow-up PR (see module docstring)."""
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    for revision in script.walk_revisions("base", heads[0]):
        module = revision.module
        upgrade = inspect.getsource(module.upgrade).lower()
        names_it = _TABLE in upgrade or getattr(module, "TABLE", None) == _TABLE
        assert not (names_it and "drop" in upgrade), f"{revision.revision} drops {_TABLE}"

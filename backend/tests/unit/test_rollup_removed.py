"""ODD `metricas-ml-tablero`, "Sin tabla resumen" ST4: the daily rollup's
code is gone -- the board reads the orders and nothing writes or reads
`ml_product_daily_metrics` any more.

Two-phase removal: the release that removed the code left the table in place,
unused (a drop run during that deploy, before the workers restart, would have
made every metrics store of the still-running old workers fail). That release
is deployed, so the follow-up migration `20261005_drop_ml_product_daily_metrics`
drops the table.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import pathlib
import re
from typing import Any, Dict, Optional

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TABLE = "ml_product_daily_metrics"


# `DROP TABLE ... ml_product_daily_metrics` within one SQL statement (never
# across a `;`), or Alembic's `op.drop_table(<the table>)`. A `DROP INDEX` on
# the table, or a file that merely mentions it, is not a drop.
_SQL_DROP = re.compile(rf"\bDROP\s+TABLE\b[^;]*\b{_TABLE}\b", re.IGNORECASE)
_OP_DROP = re.compile(r"\bop\.drop_table\(\s*(?P<arg>[^,)\s]+)")


def drops_the_table(source: str, constants: Optional[Dict[str, Any]] = None) -> bool:
    """Whether migration source drops the rollup table. `constants` (the
    module's globals) resolve a name bound to the table (`TABLE = "..."`)
    used as `op.drop_table(TABLE)` or inside an f-string (`{TABLE}`)."""
    names = {name for name, value in (constants or {}).items() if value == _TABLE}
    for name in names:
        source = source.replace("{" + name + "}", _TABLE)
    if _SQL_DROP.search(source):
        return True
    return any(m.group("arg").strip("'\"") in names | {_TABLE} for m in _OP_DROP.finditer(source))


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


_DROP_REVISION = "20261005_drop_ml_product_daily_metrics"


def test_exactly_the_follow_up_migration_drops_the_table() -> None:
    """Phase two: the release that stopped writing the table is deployed
    (2026-10-05), so the follow-up drops it -- and only that revision does."""
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    droppers = [
        revision.revision
        for revision in script.walk_revisions("base", heads[0])
        if drops_the_table(inspect.getsource(revision.module.upgrade), constants=vars(revision.module))
    ]
    assert droppers == [_DROP_REVISION]


@pytest.mark.parametrize(
    "source, drops",
    [
        ('def upgrade():\n    op.execute("DROP TABLE IF EXISTS ml_product_daily_metrics")', True),
        ("def upgrade():\n    op.execute('drop   table\n ml_product_daily_metrics cascade')", True),
        ('def upgrade():\n    op.drop_table("ml_product_daily_metrics")', True),
        ('def upgrade():\n    op.drop_table(\n        "ml_product_daily_metrics",\n    )', True),
        # Mentions the table, drops only an INDEX on it: not a table drop.
        ('def upgrade():\n    op.execute("DROP INDEX IF EXISTS ix_x ON ml_product_daily_metrics")', False),
        (
            'def upgrade():\n    op.drop_index("ix_ml_product_daily_metrics_day", table_name="ml_product_daily_metrics")',
            False,
        ),
        # Drops ANOTHER table in a file that also mentions this one.
        ('def upgrade():\n    op.drop_table("other")\n    # ml_product_daily_metrics stays', False),
        ('def upgrade():\n    op.execute("DROP TABLE other; SELECT 1 FROM ml_product_daily_metrics")', False),
    ],
)
def test_the_drop_matcher(source: str, drops: bool) -> None:
    assert drops_the_table(source) is drops

"""The TP-Link figures (metricas-ml-tplink-mode P3) are backfilled by bumping
`CURRENT_FORMULA_VERSION`: `order_metrics.reconcile` re-enqueues every stored
row below it and `order_metrics.drain` recomputes it with its TP columns.
"""

from __future__ import annotations

from app.services.order_metrics import constants
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION


def test_the_tp_columns_bumped_the_formula_version() -> None:
    assert CURRENT_FORMULA_VERSION == 7


def test_the_bump_is_documented_in_the_history() -> None:
    assert "- 7: metricas-ml-tplink-mode" in constants.__doc__

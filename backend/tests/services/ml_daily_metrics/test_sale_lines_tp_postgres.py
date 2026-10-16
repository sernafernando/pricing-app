"""TP-Link shares of the persisted sale lines (metricas-ml-tplink-mode P3):
`tg_tp`, `mtg_tp`, `mcosto_tp`, split from the order's stored Total TP and TP
cost exactly like `tg`/`mtg`/`mcosto` are split from Total Gauss and cost.

- `tg_tp`: NULL on the lines of an order with Total Gauss but no Total TP (a
  missing TP cost); 0 where `tg` is 0 (no Total Gauss).
- `mtg_tp`/`mcosto_tp`: all-or-nothing per group, like the markup: a group
  that takes part in the Gauss markup but has a member without Total TP gets
  NULL on every line (incomplete), never a partial or a 0.

Real Postgres: the writer is PostgreSQL-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.ml_sale_line import MlSaleLine
from app.services.ml_daily_metrics.sales import sale_lines
from app.services.order_metrics.sale_lines_store import STORED_COLUMNS
from app.services.order_metrics.store import store_order_metrics
from app.services.order_metrics.types import GaussStatus, OrderMetrics
from tests.services.ml_daily_metrics.seed import Line, seed_order

DAY = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
TP = ("tg_tp", "mtg_tp", "mcosto_tp")


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _metrics(
    order_id: int, tg: Optional[str], costo: str, costo_tp: Optional[str], total_tp: Optional[str]
) -> OrderMetrics:
    resolved = tg is not None
    return OrderMetrics(
        order_id=order_id,
        neto=Decimal("100.00"),
        neto_sin_iva=Decimal("82.64"),
        iva_reconcilia=True,
        costo_mercaderia=Decimal(costo),
        total_gauss=Decimal(tg) if resolved else None,
        markup_pct=None,
        gauss_status=GaussStatus.OK if resolved else GaussStatus.UNRESOLVED,
        provisional_falta=None,
        unresolved_reason=None if resolved else "sin_pagos",
        formula_version=6,
        computed_at=datetime.now(timezone.utc),
        costo_tp=Decimal(costo_tp) if costo_tp is not None else None,
        total_tp=Decimal(total_tp) if total_tp is not None else None,
        tp_incompleto=costo_tp is None,
    )


def _seed(db):
    # Pack 900, both members complete. Order 1's two items weigh 2x10 and 1x20:
    # half each.
    two = [Line(100, "MLA1", 2, Decimal("100")), Line(101, "MLA2", 1, Decimal("50"), unit_cost=Decimal("20"))]
    seed_order(db, 1, DAY, two, tg="60", costo="40", pack_id=900)
    seed_order(db, 2, DAY, [Line(102, "MLA3", 3, Decimal("10"))], tg="9", costo="6", pack_id=900)
    # Pack 901: order 4 has no TP cost.
    seed_order(db, 3, DAY, [Line(103, "MLA4", 1, Decimal("70"))], tg="25", costo="30", pack_id=901)
    seed_order(db, 4, DAY, [Line(104, "MLA5", 1, Decimal("70"))], tg="9", costo="6", pack_id=901)
    # Order 5: unresolved Total Gauss, TP cost known.
    seed_order(db, 5, DAY, [Line(105, "MLA6", 1, Decimal("70"))], tg=None, costo="30", gauss_status="unresolved")
    db.flush()
    store_order_metrics(
        db,
        {
            1: _metrics(1, "60", "40", "30", "70"),
            2: _metrics(2, "9", "6", "5", "10"),
            3: _metrics(3, "25", "30", "20", "35"),
            4: _metrics(4, "9", "6", None, None),
            5: _metrics(5, None, "30", "20", None),
        },
    )


def _stored(db) -> dict:
    table = MlSaleLine.__table__
    rows = db.execute(select(table.c.mla, *(table.c[name] for name in TP))).all()
    return {row.mla: tuple(None if v is None else Decimal(v).normalize() for v in row[1:]) for row in rows}


def _d(*values):
    return tuple(None if v is None else Decimal(v).normalize() for v in values)


@pytest.mark.postgres
class TestSaleLinesTp:
    def test_the_tp_columns_are_part_of_what_is_stored(self):
        assert set(TP) <= set(STORED_COLUMNS)

    def test_tp_shares_follow_the_gauss_rules_and_stay_null_when_incomplete(self, board_pg):
        _seed(board_pg)

        assert _stored(board_pg) == {
            "MLA1": _d("35", "35", "15"),
            "MLA2": _d("35", "35", "15"),
            "MLA3": _d("10", "10", "5"),
            # Pack 901: order 3 has its own Total TP, but the group's markup
            # needs every member's: incomplete.
            "MLA4": _d("35", None, None),
            "MLA5": _d(None, None, None),
            # No Total Gauss: no money, like `tg`.
            "MLA6": _d("0", "0", "0"),
        }

    def test_the_stored_tp_shares_are_what_sale_lines_derives(self, board_pg):
        _seed(board_pg)
        table = MlSaleLine.__table__
        lines = sale_lines(sqlite=False, queue=False, keyed=True, tp=True)

        live = board_pg.execute(select(*(lines.c[n] for n in STORED_COLUMNS)).order_by(lines.c.item_row_id)).all()
        stored = board_pg.execute(select(*(table.c[n] for n in STORED_COLUMNS)).order_by(table.c.item_row_id)).all()

        assert [tuple(r) for r in stored] == [tuple(r) for r in live]

    def test_the_board_live_derivation_does_not_carry_the_tp_shares(self):
        assert not set(TP) & set(sale_lines(sqlite=False).c.keys())

    def test_a_late_tp_cost_completes_the_group_on_recompute(self, board_pg):
        _seed(board_pg)

        store_order_metrics(board_pg, {4: _metrics(4, "9", "6", "4", "11")})

        stored = _stored(board_pg)
        assert stored["MLA4"] == _d("35", "35", "20")
        assert stored["MLA5"] == _d("11", "11", "4")

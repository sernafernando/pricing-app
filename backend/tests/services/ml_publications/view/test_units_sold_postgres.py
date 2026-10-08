"""P6.T4 (S41.1): units sold per MLA come from the SAME base as Métricas ML (`ml_daily_metrics/sales.sale_lines`).

Real Postgres, the board's tables. The assertions that matter: the figure for a publication is the sum of the
quantities of ALL its sold lines (every variation), inside the business-day period and with the board's rules for
what a sale is, and it equals what the board's own base reports for the same MLA.
"""

# ruff: noqa: F811 -- `board_pg` is the board's fixture, imported and used by name

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_daily_metrics import sales
from app.services.ml_publications.view.units_sold import UnitsSoldProvider
from tests.services.ml_daily_metrics.conftest import board_pg, board_pg_engine  # noqa: F401

pytestmark = pytest.mark.postgres

SOLD = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)  # 12:00 in Buenos Aires: the 20th
DAY = date(2026, 9, 20)
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def order(db, order_id, lines, *, accredited=SOLD, status="paid", covered=None, pack_id=None) -> None:
    """`lines`: (mla, variation_id, qty). One group row per lone order."""
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status=status,
            covered_by_marketplace=covered,
            ml_last_updated=NOW,
            date_created=accredited,
            seller_id=999,
            currency_id="ARS",
            total_amount=Decimal("100"),
            paid_amount=Decimal("100"),
        )
    )
    db.flush()
    for mla, variation_id, qty in lines:
        db.add(
            MlOrderItemOps(
                order_id=order_id, item_id=mla, variation_id=variation_id, quantity=qty, unit_price=Decimal("10")
            )
        )
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id=mla,
                variation_id=variation_id,
                costo_origen=Decimal("5"),
                moneda="ARS",
                costo_unitario_ars=Decimal("5"),
                iva_pct=21,
                precio_unitario=Decimal("10"),
                fuente="t",
                producto_item_id=77,
            )
        )
    db.add(MlPaymentOps(payment_id=order_id * 10, order_id=order_id, status="approved", date_approved=accredited))
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=Decimal("0"),
            total_gauss=Decimal("1"),
            costo_mercaderia=Decimal("1"),
            gauss_status="ok",
            formula_version=2,
            computed_at=NOW,
        )
    )
    db.flush()
    db.execute(
        text(
            "INSERT INTO ml_group_metrics (group_key, gauss_status, member_order_ids, group_date, formula_version, "
            "computed_at) VALUES (:gk, 'ok', CAST(:members AS BIGINT[]), :gd, 2, now())"
        ),
        {"gk": f"o:{order_id}", "members": "{" + str(order_id) + "}", "gd": accredited},
    )


class TestUnitsPerMla:
    def test_every_variation_of_the_publication_counts(self, board_pg) -> None:
        order(board_pg, 1, [("MLA1", 11, 2), ("MLA1", 12, 3), ("MLA2", None, 7)])
        order(board_pg, 2, [("MLA1", 11, 4)])
        got = UnitsSoldProvider().units_by_mla(board_pg, None, DAY, DAY)
        assert got == {"MLA1": 9, "MLA2": 7}
        assert all(isinstance(units, int) for units in got.values())

    def test_a_list_of_mlas_restricts_the_answer(self, board_pg) -> None:
        order(board_pg, 1, [("MLA1", None, 2), ("MLA2", None, 7)])
        assert UnitsSoldProvider().units_by_mla(board_pg, ["MLA2", "MLA404"], DAY, DAY) == {"MLA2": 7}
        assert UnitsSoldProvider().units_by_mla(board_pg, [], DAY, DAY) == {}

    def test_only_the_business_days_of_the_period_count(self, board_pg) -> None:
        order(board_pg, 1, [("MLA1", None, 1)])  # the 20th
        order(
            board_pg, 2, [("MLA1", None, 10)], accredited=datetime(2026, 9, 21, 2, 59, tzinfo=timezone.utc)
        )  # 23:59 on the 20th
        order(
            board_pg, 3, [("MLA1", None, 100)], accredited=datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)
        )  # the 21st
        order(
            board_pg, 4, [("MLA1", None, 1000)], accredited=datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc)
        )  # the 18th
        provider = UnitsSoldProvider()
        assert provider.units_by_mla(board_pg, None, DAY, DAY) == {"MLA1": 11}
        assert provider.units_by_mla(board_pg, None, date(2026, 9, 18), date(2026, 9, 21)) == {"MLA1": 1111}
        assert provider.units_by_mla(board_pg, None, date(2026, 9, 1), date(2026, 9, 10)) == {}

    def test_a_sale_cancelled_without_ml_covering_it_is_not_a_sale(self, board_pg) -> None:
        order(board_pg, 1, [("MLA1", None, 5)], status="cancelled")
        order(board_pg, 2, [("MLA1", None, 3)], status="cancelled", covered=True)
        assert UnitsSoldProvider().units_by_mla(board_pg, None, DAY, DAY) == {"MLA1": 3}

    def test_it_is_the_same_figure_the_board_base_reports(self, board_pg) -> None:
        order(board_pg, 1, [("MLA1", 11, 2), ("MLA1", 12, 3), ("MLA2", None, 7)])
        order(board_pg, 2, [("MLA1", None, 4)], status="cancelled")
        lines = sales.sale_lines(sqlite=False, ranges=[sales.day_bounds(DAY, DAY)])
        board = dict(board_pg.execute(select(lines.c.mla, func.sum(lines.c.qty)).group_by(lines.c.mla)).all())
        assert UnitsSoldProvider().units_by_mla(board_pg, None, DAY, DAY) == {k: int(v) for k, v in board.items()}

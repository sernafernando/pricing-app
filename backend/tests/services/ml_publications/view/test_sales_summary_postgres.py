"""The per-publication sales summary of the Publicaciones list: units, gross revenue and the real markup of each MLA
over the last 30 business days, read from the SAME base as Métricas ML (`ml_daily_metrics.sales`).

Real Postgres, the board's tables. What matters: the markup is the board's ratio of sums (`mtg / mcosto`), never an
average of per-order percentages; the window is the business (Buenos Aires) day; only the MLAs asked for are read;
and with `METRICAS_SALE_LINES_ENABLED` the persisted `ml_sale_lines` give the same figures as the live derivation.
"""

# ruff: noqa: F811 -- `board_pg` is the board's fixture, imported and used by name

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, update

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.services.ml_daily_metrics import board, kpi_strip
from app.services.ml_publications.view import sales_summary
from tests.services.ml_daily_metrics.conftest import board_pg, board_pg_engine  # noqa: F401
from tests.services.ml_daily_metrics.test_board_sale_lines_postgres import populate_sale_lines
from tests.services.ml_publications.view.test_units_sold_postgres import order

pytestmark = pytest.mark.postgres

TODAY = date(2026, 9, 30)
SOLD = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", False)


def priced(db, order_id, lines, *, tg, costo, **kwargs) -> None:
    """An order (see `order`) whose stored Total Gauss and merchandise cost are `tg` / `costo`."""
    order(db, order_id, lines, **kwargs)
    db.execute(
        update(MlOrderMetrics)
        .where(MlOrderMetrics.order_id == order_id)
        .values(total_gauss=Decimal(tg), costo_mercaderia=Decimal(costo))
    )
    db.flush()


def summary(db, mlas):
    return sales_summary.summary_by_mla(db, mlas, today=TODAY)


class TestWindow:
    def test_it_is_the_last_30_business_days_ending_today(self) -> None:
        assert sales_summary.window(TODAY) == (date(2026, 9, 1), TODAY)


class TestSummary:
    def test_units_gross_and_the_sales_weighted_markup(self, board_pg) -> None:
        priced(board_pg, 1, [("MLA1", None, 2)], tg="30", costo="100")
        priced(board_pg, 2, [("MLA1", None, 3)], tg="30", costo="300")

        got = summary(board_pg, ["MLA1"])["MLA1"]

        assert got.units == 5
        assert got.gross == Decimal("50.00")  # unit price 10
        # (30 + 30) / (100 + 300): 15 %, not the 20 % average of 30 % and 10 %
        assert got.markup == Decimal("15.0")

    def test_a_publication_without_sales_is_absent(self, board_pg) -> None:
        priced(board_pg, 1, [("MLA1", None, 1)], tg="1", costo="1")
        assert "MLA2" not in summary(board_pg, ["MLA1", "MLA2"])
        assert summary(board_pg, []) == {}

    def test_only_the_mlas_asked_for_are_answered(self, board_pg) -> None:
        priced(board_pg, 1, [("MLA1", None, 1), ("MLA2", None, 4)], tg="10", costo="20")
        assert set(summary(board_pg, ["MLA2"])) == {"MLA2"}

    def test_sales_outside_the_window_do_not_count(self, board_pg) -> None:
        priced(board_pg, 1, [("MLA1", None, 1)], tg="1", costo="1")
        # 23:59 of Aug 31st in Buenos Aires: the day before the window
        priced(
            board_pg,
            2,
            [("MLA1", None, 100)],
            tg="1",
            costo="1",
            accredited=datetime(2026, 9, 1, 2, 59, tzinfo=timezone.utc),
        )
        assert summary(board_pg, ["MLA1"])["MLA1"].units == 1

    def test_an_exact_half_tie_rounds_like_the_board_displays_it(self, board_pg) -> None:
        """1.15 % exactly: the board shows `round_pp` (the float's round, 1.1 -- 1.15 is 1.1499... as a float), not
        the Decimal's half-even 1.2. The same sales must read the same number on both screens."""
        priced(board_pg, 1, [("MLA1", None, 1)], tg="1.15", costo="100")
        markup = summary(board_pg, ["MLA1"])["MLA1"].markup
        assert markup == kpi_strip.round_pp(board.markup_of(Decimal("1.15"), Decimal("100"))) == 1.1

    def test_no_cost_means_no_markup_never_zero(self, board_pg) -> None:
        priced(board_pg, 1, [("MLA1", None, 2)], tg="10", costo="0")
        got = summary(board_pg, ["MLA1"])["MLA1"]
        assert got.units == 2 and got.markup is None

    def test_the_persisted_lines_give_the_same_figures(self, board_pg, monkeypatch) -> None:
        priced(board_pg, 1, [("MLA1", None, 2), ("MLA2", None, 1)], tg="30", costo="100")
        priced(board_pg, 2, [("MLA1", None, 3)], tg="30", costo="300")
        live = summary(board_pg, ["MLA1", "MLA2"])
        assert populate_sale_lines(board_pg) == 3

        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
        reads: list = []
        real = sales_summary.sales.persisted_lines
        monkeypatch.setattr(sales_summary.sales, "persisted_lines", lambda **kw: reads.append(kw) or real(**kw))

        assert summary(board_pg, ["MLA1", "MLA2"]) == live
        assert reads, "with the flag on the persisted table is the source"

    def test_the_persisted_read_is_restricted_to_the_mlas_inside_the_table_scan(self, board_pg, monkeypatch) -> None:
        """The MLAs bound the read of `ml_sale_lines` itself, not only the aggregate over it: the plan must not rely
        on Postgres pushing an outer filter down into the lines subquery."""
        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany) -> None:
            statements.append(" ".join(statement.split()))

        engine = board_pg.get_bind().engine
        event.listen(engine, "before_cursor_execute", record)
        try:
            summary(board_pg, ["MLA1", "MLA2"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        (sql,) = [s for s in statements if "ml_sale_lines" in s]
        assert "ml_sale_lines.mla IN" in sql

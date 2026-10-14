"""The Métricas ML figures of each publication on a Publicaciones page: sales windows, the 90-day series, the real
markup, the result, the last sale and the ageing -- the Board's publication rows, asked for the page's MLAs only.

Real Postgres, the board's tables. What matters: every figure is EXACTLY what Métricas ML shows for the same MLA
over the same last-30-business-days period (one metric, one source: the Board computes it, this module only asks);
one Board per page, never one per row; an MLA the Board has no row for is absent (the screen reads "—"); and with
`METRICAS_SALE_LINES_ENABLED` the persisted lines give the same figures as the live derivation.
"""

# ruff: noqa: F811 -- `board_pg` is the board's fixture, imported and used by name

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, text, update

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import row_metrics
from tests.services.ml_daily_metrics.conftest import board_pg, board_pg_engine  # noqa: F401
from tests.services.ml_daily_metrics.test_board_sale_lines_postgres import populate_sale_lines
from tests.services.ml_publications.view.test_units_sold_postgres import order

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)  # 15:00 in Buenos Aires
TODAY = date(2026, 9, 30)
THREE_DAYS_AGO = datetime(2026, 9, 27, 15, tzinfo=timezone.utc)
TWENTY_DAYS_AGO = datetime(2026, 9, 10, 15, tzinfo=timezone.utc)
FIFTY_DAYS_AGO = datetime(2026, 8, 11, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", False)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def priced(db, order_id, lines, *, tg, costo, **kwargs) -> None:
    """An order (see `order`) whose stored Total Gauss and merchandise cost are `tg` / `costo`."""
    order(db, order_id, lines, **kwargs)
    db.execute(
        update(MlOrderMetrics)
        .where(MlOrderMetrics.order_id == order_id)
        .values(total_gauss=Decimal(tg), costo_mercaderia=Decimal(costo))
    )
    db.flush()


def mirror(db, mla: str, mlp_id: int, started: str = "2026-06-01") -> None:
    """The ERP mirror's publication row: what puts a never-sold MLA on the board."""
    db.execute(
        text(
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, mlp_itemtitle, "
            "mlp_start_time) VALUES (:id, :mla, 77, :mla, CAST(:started AS TIMESTAMP))"
        ),
        {"id": mlp_id, "mla": mla, "started": started},
    )


@pytest.fixture()
def sold(board_pg):
    priced(board_pg, 1, [("MLA1", None, 2)], tg="30", costo="100", accredited=THREE_DAYS_AGO)
    priced(board_pg, 2, [("MLA1", None, 3)], tg="30", costo="300", accredited=TWENTY_DAYS_AGO)
    priced(board_pg, 3, [("MLA2", None, 4)], tg="10", costo="40", accredited=FIFTY_DAYS_AGO)
    priced(board_pg, 4, [("MLA3", None, 1)], tg="5", costo="0", accredited=THREE_DAYS_AGO)
    mirror(board_pg, "MLA4", 1)  # published, never sold
    return board_pg


def metricas(db, *mlas: str) -> dict:
    """What Métricas ML shows for these MLAs: the Board's publication view over the last 30 business days, asked
    directly and unrestricted, then picked by MLA."""
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by="publication")
    with board.Board(db, f, scope_pairs=None) as b:
        return {row.mla: row for row in b.page(None) if row.mla in mlas}


FIGURES = (
    "units",
    "gross",
    "tg",
    "mtg",
    "costo",
    "markup",
    "markup_delta",
    "windows",
    "series_units",
    "series_markup",
    "last_sale_at",
    "ageing_days",
)


class TestSameNumbersAsMetricas:
    def test_every_figure_is_the_boards_publication_row(self, sold) -> None:
        mlas = ("MLA1", "MLA2", "MLA3", "MLA4")
        got = row_metrics.metrics_by_mla(sold, list(mlas))
        expected = metricas(sold, *mlas)

        assert set(got) == set(expected) == set(mlas)
        for mla in mlas:
            for name in FIGURES:
                assert getattr(got[mla], name) == getattr(expected[mla], name), (mla, name)

    def test_the_windows_the_markup_and_the_rotation_read_as_metricas_defines_them(self, sold) -> None:
        got = row_metrics.metrics_by_mla(sold, ["MLA1", "MLA2", "MLA3", "MLA4"])

        mla1 = got["MLA1"]
        assert (mla1.windows["7d"], mla1.windows["30d"]) == (2, 5)
        assert float(mla1.markup) == 15.0  # (30 + 30) / (100 + 300): sales-weighted, not the 20 % average
        assert mla1.ageing_days == 3 and mla1.last_sale_at is not None
        assert sum(mla1.series_units) == 5 and len(mla1.series_units) == board.SERIES_DAYS

        mla2 = got["MLA2"]  # sold 50 days ago: nothing in the windows, still its last sale and ageing
        assert (mla2.windows["30d"], mla2.gross, mla2.markup) == (0, 0, None)
        assert mla2.ageing_days == 50

        assert got["MLA3"].markup is None  # no cost means no markup, never 0
        assert got["MLA4"].units == 0 and got["MLA4"].last_sale_at is None

    def test_the_persisted_lines_give_the_same_figures(self, sold, monkeypatch) -> None:
        live = row_metrics.metrics_by_mla(sold, ["MLA1", "MLA2", "MLA3"])
        assert populate_sale_lines(sold) == 4

        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
        persisted = row_metrics.metrics_by_mla(sold, ["MLA1", "MLA2", "MLA3"])

        for mla, row in live.items():
            for name in FIGURES:
                assert getattr(persisted[mla], name) == getattr(row, name), (mla, name)

    def test_the_persisted_read_is_restricted_to_the_mlas_inside_the_table_scan(self, sold, monkeypatch) -> None:
        """The page's MLAs bound the read of `ml_sale_lines` itself, not only the aggregate over it: the plan must
        not rely on Postgres pushing an outer filter down into the lines subquery."""
        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany) -> None:
            statements.append(" ".join(statement.split()))

        engine = sold.get_bind().engine
        event.listen(engine, "before_cursor_execute", record)
        try:
            row_metrics.metrics_by_mla(sold, ["MLA1", "MLA2"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        (sql,) = [s for s in statements if "FROM ml_sale_lines" in s and "max(ml_sale_lines.group_date)" not in s]
        assert "ml_sale_lines.mla IN" in sql


class TestOnlyThePage:
    def test_only_the_mlas_asked_for_are_answered(self, sold) -> None:
        assert set(row_metrics.metrics_by_mla(sold, ["MLA2", "MLA2"])) == {"MLA2"}

    def test_an_mla_the_board_has_no_row_for_is_absent(self, sold) -> None:
        assert set(row_metrics.metrics_by_mla(sold, ["MLA1", "MLA999"])) == {"MLA1"}

    def test_no_mlas_ask_nothing(self, sold, monkeypatch) -> None:
        monkeypatch.setattr(board.Board, "__enter__", lambda self: pytest.fail("no Board for an empty page"))
        assert row_metrics.metrics_by_mla(sold, []) == {}

    def test_one_board_per_page_without_pm_scoping(self, sold, monkeypatch) -> None:
        seen: list = []
        real = board.Board.__init__

        def spy(self, db, f, *args, **kwargs):
            seen.append((f.group_by, kwargs.get("scope_pairs", "missing")))
            real(self, db, f, *args, **kwargs)

        monkeypatch.setattr(board.Board, "__init__", spy)
        row_metrics.metrics_by_mla(sold, ["MLA1", "MLA2", "MLA3", "MLA4"])
        assert seen == [("publication", None)]

    def test_the_period_is_the_last_30_business_days(self) -> None:
        assert row_metrics.window(TODAY) == (date(2026, 9, 1), TODAY)

    def test_the_set_is_gone_when_done(self, sold) -> None:
        row_metrics.metrics_by_mla(sold, ["MLA1"])
        probe = text(f"SELECT to_regclass('pg_temp.{board.MLA_SET_TABLE}') IS NULL")
        assert sold.execute(probe).scalar() is True

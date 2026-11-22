"""pubml-lentitud L4: the stock audit's sales summed IN SQL over the Board's own rows (`row_metrics.summed_sales`,
`board.Board.sums_by`) answer what adding each publication's Board row with `Sales.add` answers
(`stock_audit.summed_from_rows`): every figure, the series, the Full split, for every group, with units factors,
a publication listed twice, a publication the Board has no row for, one never sold, cents shared by a pack (each
row rounded to the cent before adding), with and without sell in / sell out, live and persisted lines."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications.view import row_metrics, stock_audit
from app.services.ml_publications.view.stock_audit import Sales
from tests.services.ml_daily_metrics.conftest import board_pg, board_pg_engine  # noqa: F401
from tests.services.ml_daily_metrics.test_board_sale_lines_postgres import populate_sale_lines
from tests.services.ml_daily_metrics.test_board_sell_in_out_postgres import CONSUMPTION_DDL
from tests.services.ml_publications.view.test_row_metrics_postgres import (  # noqa: F401
    THREE_DAYS_AGO,
    _clock,
    priced,
    sold,
)
from tests.services.ml_publications.view.test_stock_audit_sales_sums import same

pytestmark = pytest.mark.postgres

HALF = Decimal("2.5")
MEMBERS = [
    ("a", "MLA1", Decimal(1)),
    ("a", "MLA2", Decimal(1)),
    ("a", "MLA1", HALF),  # a variant's publication on its base row, in base units
    ("b", "MLA1", Decimal(1)),
    ("b", "MLA1", Decimal(1)),  # listed twice: added twice
    ("c", "MLA4", Decimal(1)),  # published, never sold
    ("d", "MLA9", Decimal(1)),  # the Board has no row: absent
    ("e", "MLA3", Decimal(3)),
    ("e", "MLA4", Decimal(1)),
    ("f", "MLA5", Decimal(1)),  # a pack's shares of 100: 33.33 each, 99.99 added row by row
    ("f", "MLA6", Decimal(1)),
    ("f", "MLA7", Decimal(1)),
]


@pytest.fixture()
def world(sold):  # noqa: F811 (the imported fixture)
    priced(
        sold,
        5,
        [("MLA5", None, 1), ("MLA6", None, 1), ("MLA7", None, 1)],
        tg="100",
        costo="70",
        accredited=THREE_DAYS_AGO,
    )
    return sold


def _setup(db, monkeypatch, sell_in_out: bool, persisted: bool) -> None:
    if sell_in_out:
        db.execute(text(CONSUMPTION_DDL))
        line = db.execute(text("SELECT min(id) FROM ml_order_items_ops")).scalar_one()
        db.execute(
            text("INSERT INTO sell_in_consumos (canal, venta_ref, descuento_ars) VALUES ('ml', :ref, 50)"),
            {"ref": line},
        )
    if persisted:
        populate_sale_lines(db)
        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)


@pytest.mark.parametrize("persisted", [False, True])
@pytest.mark.parametrize("sell_in_out", [False, True])
def test_the_sql_sums_are_the_rows_added_one_by_one(world, monkeypatch, sell_in_out, persisted) -> None:
    _setup(world, monkeypatch, sell_in_out, persisted)
    sql = row_metrics.summed_sales(world, MEMBERS, sell_in_out)
    rows = stock_audit.summed_from_rows(world, MEMBERS, sell_in_out)

    assert set(sql.sums) == set(rows.sums) == {"a", "b", "c", "e", "f"}
    for key, expected in rows.sums.items():
        for name, value in expected.items():
            assert sql.sums[key][name] == value, (key, name)
    if sell_in_out:
        assert all("sell_in" not in sums for sums in sql.sums.values())  # costo SI T5: the stored sell in is ignored
    assert rows.sums["f"]["tg"] == Decimal("99.99")  # each row to the cent first, then added
    assert sql.splits == rows.splits and sql.splits  # MLA1, MLA3, MLA5-7 sold in the 30d window
    assert "MLA9" not in rows.found
    for mla in rows.found:  # every found publication's series: its own, or none sold (0 units, no markup)
        units, markups = sql.series.get(mla, sql.empty_series)
        assert (list(units), list(markups)) == (list(rows.series[mla][0]), list(rows.series[mla][1])), mla
    assert set(sql.found) == rows.found & (set(sql.series) | set(sql.splits))


@pytest.mark.parametrize("sell_in_out", [False, True])
def test_the_audits_sales_are_the_same_either_way(world, monkeypatch, sell_in_out) -> None:
    _setup(world, monkeypatch, sell_in_out, persisted=False)

    def apply(reader) -> dict[str, Sales]:
        monkeypatch.setattr(stock_audit, "summed_sales", reader)
        by_key = {key: Sales() for key, _, _ in MEMBERS}
        stock_audit._apply_sales(world, [(by_key[key], mla, factor) for key, mla, factor in MEMBERS], sell_in_out)
        return by_key

    sql, rows = apply(row_metrics.summed_sales), apply(stock_audit.summed_from_rows)
    for key in sql:
        same(sql[key], rows[key])
    assert not sql["d"].any_board_row and sql["d"].series_units == []
    assert sql["a"].unknown_30d  # the split was added (these sales have no shipping data: all of it unknown)

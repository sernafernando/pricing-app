"""Real 30D c/ SO (sell-in-costo-si D1): the Board's sold lines with their sell out added to the profit, over the
plain cost. Owner L12: "el costo siso no existe, es costo SI y SO va en la venta, como ganancia adicional". The sell
in of those lines (FIFO lots, cost bonuses) never comes off the cost nor adds to the profit: costo SI already holds
every invoice sell in and the loyalty."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import column, select, table
from sqlalchemy.dialects import postgresql

from app.services.ml_publications.view import real_so

D = Decimal


def row(**kw):
    base = dict(tg=D("1000"), mtg=D("800"), costo=D("4000"), sell_out=None, m_sell_out=None, sell_out_lineas=0)
    base.update(kw)
    return SimpleNamespace(**base)


class TestMarkup:
    def test_sell_out_adds_to_the_profit_over_the_plain_cost(self) -> None:
        r = row(sell_out=D("250"), m_sell_out=D("200"), sell_out_lineas=3)
        assert real_so.markup_so(r) == (D("800") + D("200")) / D("4000") * 100  # 25

    def test_without_sell_out_it_does_not_apply(self) -> None:
        assert real_so.markup_so(row()) is None

    def test_an_unknown_sell_out_or_no_cost_has_no_value(self) -> None:
        assert real_so.markup_so(row(sell_out_lineas=2, m_sell_out=None)) is None
        assert real_so.markup_so(row(sell_out_lineas=2, m_sell_out=D("10"), costo=D("0"))) is None


class TestTotalGauss:
    def test_sell_out_adds_to_the_total(self) -> None:
        r = row(sell_out=D("250"), m_sell_out=D("200"), sell_out_lineas=3)
        assert real_so.total_gauss_so(r) == D("1250")

    def test_without_sell_out_it_does_not_apply(self) -> None:
        assert real_so.total_gauss_so(row()) is None


def test_the_sql_figure_is_the_python_one() -> None:
    t = table("g", column("mtg"), column("costo"), column("m_sell_out"), column("sell_out_lineas"))
    sql = str(select(real_so.markup_so_sql(t.c)).compile(dialect=postgresql.dialect()))
    assert "m_sell_in" not in sql and "sell_in_lineas" not in sql
    assert "g.mtg + g.m_sell_out" in sql and "g.sell_out_lineas >" in sql

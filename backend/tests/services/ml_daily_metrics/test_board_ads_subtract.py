"""ODD `ml-billing-balance` PR 7a-ii: "Restar publicidad" subtracts Product Ads from the board.

The ads of an MLA attach to its OWNER pair only (`services/ml_ads/owner.py`), by AD day (never the sale
day), net of IVA through `ads_cost_net_of_iva`. Total Gauss and the markup numerator drop by that amount;
the markup denominator (`costo`) never changes. DERIVED fixtures: the arithmetic is chosen so every figure
is checkable by hand (no ML capture is involved; the cost basis is the single IVA function's).
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from decimal import Decimal
from typing import List

from sqlalchemy import event

from app.models.ml_ads import MlAdsDayLedger, MlAdsItemDay
from app.services.ml_daily_metrics import board
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _day,
    _frozen_clock,
    _producto,
    _pub,
    bg_sessions,
    board_data,
)

FROM, TO = date(2026, 9, 1), date(2026, 9, 7)  # comparison period: 2026-08-25 .. 2026-08-31
OFF = board.BoardFilter(date_from=FROM, date_to=TO, solo_con_ventas=False)
ON = dataclasses.replace(OFF, restar_publicidad=True)


def _ad(db, mla: str, day: date, cost: str, ad_group: int = 1) -> None:
    db.add(MlAdsItemDay(advertiser_id=1, ad_group_id=ad_group, item_id=mla, day=day, cost=Decimal(cost), raw={}))


def _ledger(db, first: date, last: date, skip: tuple = ()) -> None:
    day = first
    while day <= last:
        if day not in skip:
            db.add(MlAdsDayLedger(source="product_ads", advertiser_id=1, day=day, status="closed"))
        day += timedelta(days=1)


def _rows(db, f: board.BoardFilter) -> dict:
    with board.Board(db, f, scope_pairs=None) as b:
        return {row.key: row for row in b.page(50, with_series=False)}


def _one_product(db, tg: str, costo: str, ads: str, sale_day: date = date(2026, 9, 3), ad_day: date = date(2026, 9, 4)):
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", sale_day, 1, "1000", tg, costo)
    _ad(db, "MLA1", ad_day, ads)
    db.commit()


def test_total_gauss_and_markup_numerator_drop_by_the_ads_and_the_denominator_stays(db) -> None:
    _one_product(db, "300", "400", "60")
    row = _rows(db, ON)["11"]
    assert (row.tg, row.mtg, row.costo) == (Decimal("240.00"), Decimal("240.00"), Decimal("400.00"))
    assert row.markup == Decimal("60")  # (300 - 60) * 100 / 400; the ads are never in the denominator
    assert row.ads_cost == Decimal("60.00")


def test_off_ignores_the_ads_and_has_no_ads_cost(db) -> None:
    _one_product(db, "300", "400", "60")
    row = _rows(db, OFF)["11"]
    assert (row.tg, row.mtg, row.markup) == (Decimal("300.00"), Decimal("300.00"), Decimal("75"))
    assert row.ads_cost is None


def test_markup_may_go_negative(db) -> None:
    _one_product(db, "50", "100", "80")
    assert _rows(db, ON)["11"].markup == Decimal("-30")


def test_markup_is_null_when_there_is_no_cost(db) -> None:
    _one_product(db, "50", "0", "20")
    row = _rows(db, ON)["11"]
    assert row.tg == Decimal("30.00") and row.markup is None


def test_an_ad_day_that_is_not_the_sale_day_is_subtracted(db) -> None:
    """Ad on 09-05 (in range), the only sale on 09-10 (out of range): the owner pair exists, so it pays."""
    _one_product(db, "300", "400", "60", sale_day=date(2026, 9, 10), ad_day=date(2026, 9, 5))
    row = _rows(db, ON)["11"]
    assert (row.units, row.tg) == (0, Decimal("-60.00"))


def test_ads_outside_the_period_are_not_subtracted(db) -> None:
    _one_product(db, "300", "400", "60", ad_day=date(2026, 9, 8))
    assert _rows(db, ON)["11"].tg == Decimal("300.00")


def test_only_the_owner_pair_pays_the_ads_of_an_mla(db) -> None:
    """MLA1 is published under product 11 (the owner) but product 12 also sold it: only 11 is charged."""
    _producto(db, 11, "Impresora", "Epson")
    _producto(db, 12, "Notebook", "Lenovo")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")
    _day(db, 12, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")
    _ad(db, "MLA1", date(2026, 9, 4), "60")
    db.commit()
    rows = _rows(db, ON)
    assert (rows["11"].tg, rows["12"].tg) == (Decimal("240.00"), Decimal("300.00"))


def test_two_ad_groups_of_the_same_mla_sum(db) -> None:
    _one_product(db, "300", "400", "60")
    _ad(db, "MLA1", date(2026, 9, 4), "40", ad_group=2)
    db.commit()
    assert _rows(db, ON)["11"].tg == Decimal("200.00")


def test_publication_view_charges_the_mla_row(db) -> None:
    _one_product(db, "300", "400", "60")
    rows = _rows(db, dataclasses.replace(ON, group_by="publication"))
    assert rows["MLA1"].tg == Decimal("240.00")


def test_previous_period_is_null_when_the_comparison_has_a_missing_ledger_day(db) -> None:
    _one_product(db, "300", "400", "60")
    _day(db, 11, "MLA1", date(2026, 8, 28), 1, "1000", "200", "400")
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31), skip=(date(2026, 8, 29),))
    db.commit()
    row = _rows(db, ON)["11"]
    assert (row.prev_tg, row.prev_mtg, row.markup_prev, row.markup_delta) == (None, None, None, None)
    assert row.markup == Decimal("60")  # the current period is untouched by the gap


def test_previous_period_is_adjusted_when_every_comparison_day_is_ledgered(db) -> None:
    _one_product(db, "300", "400", "60")
    _day(db, 11, "MLA1", date(2026, 8, 28), 1, "1000", "200", "400")
    _ad(db, "MLA1", date(2026, 8, 27), "40")
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31))
    db.commit()
    row = _rows(db, ON)["11"]
    assert (row.prev_tg, row.markup_prev) == (Decimal("160.00"), Decimal("40"))  # (200 - 40) * 100 / 400
    assert row.markup_delta == Decimal("20")


def test_ads_cost_sorts_and_is_a_margin_sort(db) -> None:
    assert "ads_cost" in board.SORTS and "ads_cost" in board.MARGIN_SORTS
    _producto(db, 11, "Impresora", "Epson")
    _producto(db, 12, "Notebook", "Lenovo")
    _pub(db, 1, "MLA1", 11, 57997)
    _pub(db, 2, "MLA2", 12, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")
    _day(db, 12, "MLA2", date(2026, 9, 3), 1, "1000", "300", "400")
    _ad(db, "MLA1", date(2026, 9, 4), "10")
    _ad(db, "MLA2", date(2026, 9, 4), "50")
    db.commit()
    desc = dataclasses.replace(ON, sort="ads_cost", sort_desc=True)
    with board.Board(db, desc, scope_pairs=None) as b:
        assert [r.key for r in b.page(10, with_series=False)] == ["12", "11"]


def test_sorting_by_ads_cost_with_the_toggle_off_still_answers(db) -> None:
    _one_product(db, "300", "400", "60")
    assert list(_rows(db, dataclasses.replace(OFF, sort="ads_cost"))) == ["11"]


def test_margin_falling_alert_reads_the_adjusted_markup(db) -> None:
    """Markup 75 -> 60 after the ads, against a previous 65 (ledgered): 60 < 65 - 1, so the alert fires only ON."""
    _one_product(db, "300", "400", "60")
    _day(db, 11, "MLA1", date(2026, 8, 28), 1, "1000", "260", "400")
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31))
    db.commit()
    falling = dataclasses.replace(OFF, alerts=("margen_cayendo",))
    assert _rows(db, falling) == {}
    assert list(_rows(db, dataclasses.replace(falling, restar_publicidad=True))) == ["11"]


def test_off_emits_no_ads_statement(db) -> None:
    _one_product(db, "300", "400", "60")
    seen: List[str] = []

    def record(conn, cursor, statement, *rest) -> None:
        seen.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        _rows(db, OFF)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert seen and not [sql for sql in seen if "ml_ads_" in sql or "board_ads_lines" in sql]


def test_the_response_carries_the_ads_only_when_the_toggle_is_on(client, admin_auth_headers, db, board_data) -> None:
    _ad(db, "MLA1", date(2026, 9, 30), "12.50")
    db.commit()
    params = {"solo_con_ventas": "true", "date_from": "2026-09-01", "date_to": "2026-09-30"}
    off = client.get(URL, params=params, headers=admin_auth_headers).json()["rows"]
    on = client.get(URL, params={**params, "restar_publicidad": "true", "sort": "ads_cost"}, headers=admin_auth_headers)
    assert on.status_code == 200, on.text
    assert all(row["ads"] is None for row in off)
    by_key = {row["key"]: row for row in on.json()["rows"]}
    assert by_key["11"]["ads"] == {"cost": 12.5}
    assert on.json()["rows"][0]["key"] == "11"  # sorted by ads cost, descending by default


def test_a_covered_comparison_with_no_rows_left_is_zero_not_null(db) -> None:
    """Every comparison day is ledgered but the filter keeps nothing: the previous KPI is a real 0, not "unknown"."""
    _one_product(db, "300", "400", "60")
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31))
    db.commit()
    nothing = dataclasses.replace(ON, q="no-such-product")
    with board.Board(db, nothing, scope_pairs=None) as b:
        kpis = b.kpis()
    assert (kpis.prev_tg, kpis.prev_mtg) == (Decimal("0.00"), Decimal("0.00"))

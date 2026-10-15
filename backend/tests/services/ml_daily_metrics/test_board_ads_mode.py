"""ODD `ml-billing-balance` PR 7b-iii-a: the 3-position ads toggle (owner decision, Engram #2720).

OFF subtracts nothing; "mla" (`restar_publicidad=true`, unchanged) subtracts the ads attributed to MLAs;
"todo" also subtracts what no publication owns at account level (Display, Brand Ads) from the KPI totals.
That spend cannot be allocated to rows, so only the unfiltered view carries it and the response says what was
APPLIED. DERIVED fixtures: the figures are chosen to be checkable by hand (no ML capture is involved).
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.ml_ads import MlAdsBrandDay, MlAdsDayLedger, MlAdsDisplayCampaignDay
from app.routers.ml_metricas import _margin_gate
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import build_board_kpis
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _day,
    _frozen_clock,
    _producto,
    _pub,
    bg_sessions,
    board_data,
)
from tests.services.ml_daily_metrics.test_board_ads_subtract import FROM, ON, _ad, _ledger

AD_DAY = date(2026, 9, 4)
MLA = dataclasses.replace(ON, solo_con_ventas=True)
TODO = dataclasses.replace(MLA, restar_todo=True)


def _display(db, cost: str, day: date = AD_DAY) -> None:
    db.add(MlAdsDisplayCampaignDay(advertiser_id=25713, campaign_id=1, day=day, consumed_budget=Decimal(cost), raw={}))


def _brand(db, cost: str, day: date = AD_DAY) -> None:
    db.add(MlAdsBrandDay(advertiser_id=25713, day=day, cost=Decimal(cost), raw={}))


def _sale_with_ads(db) -> None:
    """Product 11: Total Gauss 300 / costo 400, 100 of Product Ads, 1,200 Display and 500 Brand Ads in range."""
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")
    _ad(db, "MLA1", AD_DAY, "100")
    _display(db, "1200")
    _brand(db, "500")
    db.commit()


def _kpis(db, f: board.BoardFilter, scope_pairs=None):
    with board.Board(db, f, scope_pairs=scope_pairs) as b:
        k = b.kpis()
        rows = {row.key: row for row in b.page(50, with_series=False)}
    return k, build_board_kpis(k, True), rows


# ── the contract of the new field ──


def test_todo_needs_the_toggle_on() -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(board.BoardFilter(date_from=FROM, date_to=FROM), restar_todo=True)


def test_the_new_field_is_navigation_not_a_filter() -> None:
    assert "restar_todo" in board.NAVIGATION_FIELDS and board.is_unfiltered(TODO, None)


def test_todo_is_a_margin_feature() -> None:
    with pytest.raises(HTTPException) as err:
        _margin_gate(TODO, can_see_margin=False)
    assert err.value.status_code == 403


# ── the positions ──


def test_position_one_subtracts_only_the_mlas(db) -> None:
    _sale_with_ads(db)
    k, out, rows = _kpis(db, MLA)
    assert k.tg == Decimal("200.00")  # 300 - 100: Display and Brand Ads are not subtracted
    ads = out.ads
    assert (ads.requested, ads.applied, ads.subtracted_total) == ("mla", "mla", 100.0)


def test_position_two_also_subtracts_display_and_brand_from_the_kpi_totals(db) -> None:
    _sale_with_ads(db)
    k, out, rows = _kpis(db, TODO)
    assert (k.tg, k.mtg, k.costo) == (Decimal("-1500.00"), Decimal("-1500.00"), Decimal("400.00"))
    assert (out.total_gauss.value, out.markup.value) == (-1500.0, -375.0)  # the denominator never moves
    ads = out.ads
    assert (ads.requested, ads.applied, ads.cost_total, ads.subtracted_total) == ("todo", "todo", 100.0, 1800.0)
    assert rows["11"].tg == Decimal("200.00")  # rows only carry what a row can own


def test_position_two_without_account_level_spend_equals_position_one(db) -> None:
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")
    _ad(db, "MLA1", AD_DAY, "100")
    db.commit()
    assert _kpis(db, TODO)[0].tg == _kpis(db, MLA)[0].tg == Decimal("200.00")


@pytest.mark.parametrize("narrowing", [{"marcas": ("Epson",)}, {"q": "impresora"}], ids=["marca", "search"])
def test_a_filtered_view_applies_position_one_and_says_so(db, narrowing) -> None:
    _sale_with_ads(db)
    k, out, _rows = _kpis(db, dataclasses.replace(TODO, **narrowing))
    assert k.tg == Decimal("200.00")
    assert (out.ads.requested, out.ads.applied) == ("todo", "mla")


def test_a_pm_scoped_view_applies_position_one_and_says_so(db) -> None:
    _sale_with_ads(db)
    k, out, _rows = _kpis(db, TODO, scope_pairs=[("EPSON", "CAT")])
    assert (k.tg, out.ads.applied) == (Decimal("200.00"), "mla")


# ── the comparison period ──


def _compare(db, with_account_spend: bool = True) -> None:
    _sale_with_ads(db)
    _day(db, 11, "MLA1", date(2026, 8, 28), 1, "1000", "260", "400")
    if with_account_spend:
        _display(db, "100", date(2026, 8, 27))
        _brand(db, "50", date(2026, 8, 27))
    db.commit()


def _ledger_account(db, skip: tuple = ()) -> None:
    for source, advertiser in (("display", 25713), ("brand_ads", 25713)):
        for n in range(7):
            day = date(2026, 8, 25) + timedelta(days=n)
            if (source, day) not in skip:
                db.add(MlAdsDayLedger(source=source, advertiser_id=advertiser, day=day, status="closed"))


def test_the_previous_period_carries_the_account_level_when_every_day_is_ledgered(db) -> None:
    _compare(db)
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31))
    _ledger_account(db)
    db.commit()
    k = _kpis(db, TODO)[0]
    assert k.prev_tg == Decimal("110.00")  # 260 - 100 - 50


def test_the_previous_period_is_null_when_an_account_level_day_was_never_fetched(db) -> None:
    _compare(db)
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31))
    _ledger_account(db, skip=(("display", date(2026, 8, 29)),))
    db.commit()
    assert _kpis(db, TODO)[0].prev_tg is None
    assert _kpis(db, MLA)[0].prev_tg == Decimal("260.00")  # position one does not depend on the account level


# ── the request ──


@pytest.mark.parametrize(
    "params, status",
    [
        ({}, 200),
        ({"restar_publicidad": "true"}, 200),
        ({"publicidad": "mla"}, 200),
        ({"publicidad": "todo"}, 200),
        ({"publicidad": "off"}, 200),
        ({"publicidad": "mla", "restar_publicidad": "true"}, 200),
        ({"publicidad": "off", "restar_publicidad": "false"}, 200),
        ({"publicidad": "todo", "restar_publicidad": "true"}, 422),
        ({"publicidad": "todo", "restar_publicidad": "false"}, 422),
        ({"publicidad": "mla", "restar_publicidad": "false"}, 422),
        ({"publicidad": "off", "restar_publicidad": "true"}, 422),
        ({"publicidad": "algo"}, 422),
    ],
)
def test_the_mode_parameter_and_the_legacy_boolean_must_agree(
    client, admin_auth_headers, board_data, params, status
) -> None:
    got = client.get(
        URL, params={"date_from": "2026-09-01", "date_to": "2026-09-30", **params}, headers=admin_auth_headers
    )
    assert got.status_code == status, got.text


def test_the_response_reports_requested_and_applied_per_position(client, admin_auth_headers, db, board_data) -> None:
    _display(db, "40", date(2026, 9, 30))
    db.commit()
    base = {"date_from": "2026-09-01", "date_to": "2026-09-30"}

    def ads(**extra):
        return client.get(URL, params={**base, **extra}, headers=admin_auth_headers).json()["kpis"]["ads"]

    assert ads() is None and ads(publicidad="off") is None
    assert (ads(restar_publicidad="true")["applied"], ads(publicidad="mla")["applied"]) == ("mla", "mla")
    assert (ads(publicidad="todo")["requested"], ads(publicidad="todo")["applied"]) == ("todo", "todo")
    assert ads(publicidad="todo", marcas="Epson")["applied"] == "mla"

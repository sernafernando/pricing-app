"""ODD `ml-billing-balance` PR 7b-iii-b: what the board's ads block admits it does not know (MA-5, MA-7).

`kpis.ads.coverage` lists the days of the range the ads ledger never closed (never "zero spend"), the days it
closed with a mismatch, `data_through` and whether any data exists at all. `kpis.ads.unattributed` carries the
spend no row owns, only in the unfiltered view. DERIVED fixtures: figures chosen to be checkable by hand.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
from datetime import date

from app.models.ml_ads import MlAdsDayLedger
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import build_board_kpis
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    bg_sessions,
    board_data,
)
from tests.services.ml_daily_metrics.test_board_ads_mode import MLA, TODO, _ad, _display, _sale_with_ads
from tests.services.ml_daily_metrics.test_board_ads_subtract import FROM, TO, _ledger


def _ads(db, f: board.BoardFilter, scope_pairs=None):
    with board.Board(db, f, scope_pairs=scope_pairs) as b:
        return build_board_kpis(b.kpis(), True).ads


def _closed(db, first: date, last: date, source: str = "product_ads", skip: tuple = ()) -> None:
    for n in range((last - first).days + 1):
        day = date.fromordinal(first.toordinal() + n)
        if day not in skip:
            db.add(MlAdsDayLedger(source=source, advertiser_id=25713, day=day, status="closed"))


def test_the_days_the_ledger_never_closed_are_listed_not_counted_as_zero(db) -> None:
    _sale_with_ads(db)
    _ledger(db, FROM, TO, skip=(date(2026, 9, 2), date(2026, 9, 5)))
    db.commit()
    coverage = _ads(db, MLA).coverage
    assert coverage.available is True
    assert [(d.source, d.day.isoformat(), d.status) for d in coverage.missing_days] == [
        ("product_ads", "2026-09-02", None),
        ("product_ads", "2026-09-05", None),
    ]
    assert coverage.data_through == date(2026, 9, 1)  # the first hole ends the trusted run
    assert coverage.mismatch_days == []


def test_a_mismatch_day_is_listed_apart(db) -> None:
    _sale_with_ads(db)
    _ledger(db, FROM, TO)
    db.query(MlAdsDayLedger).filter_by(day=date(2026, 9, 3)).update({"status": "mismatch"})
    db.commit()
    coverage = _ads(db, MLA).coverage
    assert [d.day.isoformat() for d in coverage.mismatch_days] == ["2026-09-03"]
    assert coverage.missing_days == []  # a mismatch day still counts as covered


def test_without_any_ledger_row_there_is_no_data_to_trust(db) -> None:
    _sale_with_ads(db)
    coverage = _ads(db, MLA).coverage
    assert (coverage.available, coverage.data_through, coverage.missing_days) == (False, None, [])


def test_account_level_days_matter_only_in_position_two(db) -> None:
    _sale_with_ads(db)
    _ledger(db, FROM, TO)
    _closed(db, FROM, TO, "display", skip=(date(2026, 9, 6),))
    _closed(db, FROM, TO, "brand_ads")
    db.commit()
    assert _ads(db, MLA).coverage.missing_days == []
    assert [(d.source, d.day.isoformat()) for d in _ads(db, TODO).coverage.missing_days] == [("display", "2026-09-06")]


def test_a_filtered_view_still_reports_its_coverage(db) -> None:
    _sale_with_ads(db)
    _ledger(db, FROM, TO, skip=(date(2026, 9, 2),))
    db.commit()
    narrowed = _ads(db, dataclasses.replace(MLA, marcas=("Epson",)))
    assert [d.day.isoformat() for d in narrowed.coverage.missing_days] == ["2026-09-02"]


# ── the unattributed block ──


def test_the_unfiltered_view_reports_the_spend_no_row_owns(db) -> None:
    _sale_with_ads(db)
    _ad(db, "MLAX", date(2026, 9, 4), "30")  # owned by nobody
    db.commit()
    mla, todo = _ads(db, MLA).unattributed, _ads(db, TODO).unattributed
    assert mla.sin_producto_cost == 30.0
    assert (mla.account_level.display.cost_net, mla.account_level.display.subtracted) == (1200.0, False)
    assert (mla.account_level.brand.cost, mla.account_level.brand.subtracted) == (500.0, False)
    assert (todo.account_level.display.subtracted, todo.account_level.brand.subtracted) == (True, True)


def test_a_filtered_or_pm_scoped_view_has_no_unattributed_block(db) -> None:
    _sale_with_ads(db)
    assert _ads(db, dataclasses.replace(MLA, marcas=("Epson",))).unattributed is None
    assert _ads(db, MLA, scope_pairs=[("EPSON", "CAT")]).unattributed is None


def test_the_response_carries_both_blocks(client, admin_auth_headers, db, board_data) -> None:
    _display(db, "40", date(2026, 9, 30))
    _closed(db, date(2026, 9, 1), date(2026, 9, 30), "display")
    db.commit()
    params = {"date_from": "2026-09-01", "date_to": "2026-09-30", "publicidad": "mla"}
    body = client.get(URL, params=params, headers=admin_auth_headers).json()["kpis"]["ads"]
    assert body["coverage"]["available"] is False  # nothing ledgered for Product Ads
    assert body["unattributed"]["account_level"]["display"]["cost_net"] == 40.0
    filtered = client.get(URL, params={**params, "marcas": "Epson"}, headers=admin_auth_headers).json()
    assert filtered["kpis"]["ads"]["unattributed"] is None

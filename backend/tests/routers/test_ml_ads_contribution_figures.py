"""ml-ads-contribution-redesign T1 (S6) -- the contribution figures the loading page shows.

`GET /api/ml-ads/campaigns` carries each campaign's `contribution` in the range and its `advertiser_name`;
`GET /api/ml-ads/contributions/preview` answers the modal line, taking the create body as its query. Both follow the Métricas ML board's
rule over the item rows (`ml_ads_item_days`). Campaigns, item days and contributions are DERIVED rows in the SQLite
test DB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution, MlAdsItemDay
from tests.routers.test_ml_publications_links import grant

BASE = "/api/ml-ads"
GANANCIA = "ml_metricas.ver_ganancia"
ADV, UNKNOWN_ADV = 714700, 999
PCT, FULL, REFUND, NONE = 351001, 351002, 351003, 351004
OCTOBER = {"date_from": "2026-10-01", "date_to": "2026-10-31"}
FIRST_HALF = {"date_from": "2026-10-01", "date_to": "2026-10-15"}


def _item_day(db, campaign_id: int, day: date, cost: str, advertiser_id: int = ADV, item: str = "MLA1") -> None:
    db.add(
        MlAdsItemDay(
            advertiser_id=advertiser_id,
            ad_group_id=campaign_id,  # one ad group per campaign
            item_id=item,
            day=day,
            campaign_id=campaign_id,
            cost=Decimal(cost),
            raw={},
        )
    )


def _contribution(db, campaign_id: int, kind: str, value: str, settlement=None) -> None:
    db.add(
        MlAdsCampaignContribution(
            advertiser_id=ADV,
            campaign_id=campaign_id,
            kind=kind,
            value=Decimal(value),
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
            settlement=settlement,
            created_by_id=7,
            updated_by_id=7,
        )
    )


@pytest.fixture()
def figures(db, rol_ventas):
    grant(db, rol_ventas, GANANCIA)
    for campaign_id in (PCT, FULL, REFUND, NONE):
        db.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=campaign_id, name=str(campaign_id), raw={}))
    db.add(MlAdsCampaign(advertiser_id=UNKNOWN_ADV, campaign_id=1, name="other", raw={}))
    # 100 spent in each half of October on every campaign, two item rows on the first day of PCT.
    for campaign_id in (PCT, FULL, REFUND, NONE):
        _item_day(db, campaign_id, date(2026, 10, 5), "60")
        _item_day(db, campaign_id, date(2026, 10, 20), "100")
    _item_day(db, PCT, date(2026, 10, 5), "40", item="MLA2")
    for campaign_id in (FULL, REFUND, NONE):
        _item_day(db, campaign_id, date(2026, 10, 5), "40", item="MLA2")
    _item_day(db, 0, date(2026, 10, 5), "500")  # an ad group without a campaign belongs to no contribution
    _contribution(db, PCT, "percentage", "30")
    _contribution(db, FULL, "fixed_amount", "300", "full")
    _contribution(db, REFUND, "fixed_amount", "300", "refund_difference")
    db.flush()


def _campaigns(client, auth_headers, params) -> dict:
    response = client.get(f"{BASE}/campaigns", headers=auth_headers, params=params)
    assert response.status_code == 200
    return {(c["advertiser_id"], c["campaign_id"]): c for c in response.json()["campaigns"]}


def test_each_campaign_carries_the_contribution_the_board_subtracts(client, auth_headers, figures) -> None:
    october = _campaigns(client, auth_headers, OCTOBER)
    assert {cid: october[(ADV, cid)]["contribution"] for cid in (PCT, FULL, REFUND, NONE)} == {
        PCT: 60.0,  # 30% of 200
        FULL: 300.0,  # the whole amount, more than the 200 spent
        REFUND: 200.0,  # at most what the range spent
        NONE: 0.0,
    }
    half = _campaigns(client, auth_headers, FIRST_HALF)
    assert {cid: half[(ADV, cid)]["contribution"] for cid in (PCT, FULL, REFUND)} == {
        PCT: 30.0,
        FULL: 150.0,  # the window spent half of the range's 200, so it carries half of the counted amount
        REFUND: 100.0,
    }


def test_each_campaign_names_its_advertiser_when_known(client, auth_headers, figures) -> None:
    found = _campaigns(client, auth_headers, OCTOBER)
    assert found[(ADV, PCT)]["advertiser_name"] == "TPLINK"
    assert found[(UNKNOWN_ADV, 1)]["advertiser_name"] is None


def _preview(client, auth_headers, **body):
    params = {"advertiser_id": ADV, "campaign_id": PCT, **OCTOBER, **body}
    return client.get(f"{BASE}/contributions/preview", headers=auth_headers, params=params)


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"kind": "percentage", "value": "30"}, {"spend": 200.0, "counted": 60.0, "net": 140.0}),
        (
            {"kind": "fixed_amount", "value": "500", "settlement": "refund_difference"},
            {"spend": 200.0, "counted": 200.0, "net": 0.0},
        ),
        (
            {"kind": "fixed_amount", "value": "500", "settlement": "full"},
            {"spend": 200.0, "counted": 500.0, "net": -300.0},
        ),
        (
            {"kind": "fixed_amount", "value": "50", "settlement": "refund_difference"},
            {"spend": 200.0, "counted": 50.0, "net": 150.0},
        ),
        # A range that spent nothing has nothing to spread a fixed amount over: the board counts none of it.
        (
            {"campaign_id": 351099, "kind": "fixed_amount", "value": "500", "settlement": "full"},
            {"spend": 0.0, "counted": 0.0, "net": 0.0},
        ),
    ],
)
def test_the_preview_counts_like_the_board_without_writing(client, db, auth_headers, figures, body, expected) -> None:
    before = db.query(MlAdsCampaignContribution).count()
    response = _preview(client, auth_headers, **body)
    assert response.status_code == 200
    assert response.json() == expected
    assert db.query(MlAdsCampaignContribution).count() == before


def test_the_preview_rejects_a_body_the_form_could_not_save(client, auth_headers, figures) -> None:
    response = _preview(client, auth_headers, kind="fixed_amount", value="500")  # no settlement
    assert response.status_code == 422


def test_the_preview_needs_ver_ganancia(client, auth_headers) -> None:
    response = _preview(client, auth_headers, kind="percentage", value="30")
    assert response.status_code == 403

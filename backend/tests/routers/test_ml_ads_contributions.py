"""ml-ads-brand-contribution T1a -- `GET /api/ml-ads/campaigns` (S8): every catalogued Product Ads campaign with its
brand contributions and its cost in the range. Campaigns, days and contributions are DERIVED rows in the SQLite test DB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution, MlAdsCampaignDay
from tests.routers.test_ml_publications_links import grant

BASE = "/api/ml-ads"
GANANCIA = "ml_metricas.ver_ganancia"
ADV, CAMP, OTHER = 714700, 351001, 351002
RANGE = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


@pytest.fixture()
def campaigns(db):
    for campaign_id, name in ((CAMP, "TP-Link routers"), (OTHER, "Epson")):
        db.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=campaign_id, name=name, status="active", raw={}))
    for day, cost in ((date(2026, 10, 4), "100.50"), (date(2026, 10, 5), "200.25"), (date(2026, 11, 1), "999")):
        db.add(MlAdsCampaignDay(advertiser_id=ADV, campaign_id=CAMP, day=day, cost=Decimal(cost), raw={}))
    for kind, value, start, end, settlement in (
        ("fixed_amount", "50.00", date(2026, 11, 1), date(2026, 11, 30), "full"),
        ("percentage", "30.00", date(2026, 10, 1), date(2026, 10, 31), None),
    ):
        db.add(
            MlAdsCampaignContribution(
                advertiser_id=ADV,
                campaign_id=CAMP,
                kind=kind,
                value=Decimal(value),
                date_from=start,
                date_to=end,
                settlement=settlement,
                brand="TP-Link",
                created_by_id=7,
                updated_by_id=7,
            )
        )
    db.flush()


def test_viewing_needs_ver_ganancia(client, auth_headers, campaigns) -> None:
    response = client.get(f"{BASE}/campaigns", headers=auth_headers, params=RANGE)
    assert response.status_code == 403
    assert GANANCIA in response.json()["error"]["message"]


def test_an_inverted_range_is_422(client, db, rol_ventas, auth_headers) -> None:
    grant(db, rol_ventas, GANANCIA)
    response = client.get(f"{BASE}/campaigns", headers=auth_headers, params={**RANGE, "date_from": "2026-11-01"})
    assert response.status_code == 422


def test_each_campaign_carries_its_contributions_and_its_cost_in_the_range(
    client, db, rol_ventas, auth_headers, campaigns
) -> None:
    grant(db, rol_ventas, GANANCIA)
    response = client.get(f"{BASE}/campaigns", headers=auth_headers, params=RANGE)
    assert response.status_code == 200
    found = {c["campaign_id"]: c for c in response.json()["campaigns"]}
    assert set(found) == {CAMP, OTHER}
    mine = found[CAMP]
    assert (mine["advertiser_id"], mine["name"], mine["status"], mine["cost"]) == (
        ADV,
        "TP-Link routers",
        "active",
        300.75,
    )
    assert [(c["kind"], c["value"], c["date_from"], c["date_to"], c["settlement"]) for c in mine["contributions"]] == [
        ("percentage", 30.0, "2026-10-01", "2026-10-31", None),  # by start, every contribution of the campaign
        ("fixed_amount", 50.0, "2026-11-01", "2026-11-30", "full"),
    ]
    assert (mine["contributions"][0]["brand"], mine["contributions"][0]["created_by_id"]) == ("TP-Link", 7)
    assert (found[OTHER]["cost"], found[OTHER]["contributions"]) == (0.0, [])

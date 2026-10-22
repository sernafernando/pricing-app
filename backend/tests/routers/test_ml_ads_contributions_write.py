"""ml-ads-brand-contribution T1b-i, T1b-ii -- `POST/PUT/DELETE /api/ml-ads/contributions` (S4, S7).

Managing needs `ml_metricas.gestionar_aportes_ads` on top of the router's `ml_metricas.ver_ganancia`. Campaigns are
DERIVED rows in the SQLite test DB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution
from tests.routers.test_ml_publications_links import grant

BASE = "/api/ml-ads"
GANANCIA = "ml_metricas.ver_ganancia"
GESTIONAR = "ml_metricas.gestionar_aportes_ads"
ADV, CAMP, OTHER = 714700, 351001, 351002


def _contribution(**overrides) -> dict:
    body = {
        "advertiser_id": ADV,
        "campaign_id": CAMP,
        "kind": "percentage",
        "value": "30",
        "date_from": "2026-10-01",
        "date_to": "2026-10-31",
        "brand": "TP-Link",
        "note": "Q4 co-op",
    }
    body.update(overrides)
    return body


@pytest.fixture()
def campaigns(db):
    for campaign_id, name in ((CAMP, "TP-Link routers"), (OTHER, "Epson")):
        db.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=campaign_id, name=name, status="active", raw={}))
    db.flush()


@pytest.fixture()
def manager(db, rol_admin, admin_auth_headers, campaigns):
    grant(db, rol_admin, GANANCIA, GESTIONAR)
    return admin_auth_headers


@pytest.fixture()
def viewer(db, rol_ventas, auth_headers, campaigns):
    grant(db, rol_ventas, GANANCIA)
    return auth_headers


def _rows(db) -> list[MlAdsCampaignContribution]:
    db.expire_all()
    return db.query(MlAdsCampaignContribution).order_by(MlAdsCampaignContribution.id).all()


def _create(client, headers, **overrides):
    return client.post(f"{BASE}/contributions", headers=headers, json=_contribution(**overrides))


class TestPermissions:
    def test_ver_ganancia_alone_views_but_cannot_manage(self, client, db, viewer, manager) -> None:
        created = _create(client, manager).json()
        listed = client.get(
            f"{BASE}/campaigns", headers=viewer, params={"date_from": "2026-10-01", "date_to": "2026-10-31"}
        )
        assert listed.status_code == 200
        responses = [
            _create(client, viewer, campaign_id=OTHER),
            client.put(f"{BASE}/contributions/{created['id']}", headers=viewer, json=_contribution(value="10")),
            client.delete(f"{BASE}/contributions/{created['id']}", headers=viewer),
        ]
        assert [r.status_code for r in responses] == [403, 403, 403]
        assert GESTIONAR in responses[0].json()["error"]["message"]
        assert [(r.campaign_id, r.value) for r in _rows(db)] == [(CAMP, Decimal("30.00"))]


class TestCreate:
    def test_a_percentage_is_stored_with_who_loaded_it(self, client, db, manager, admin_user) -> None:
        response = _create(client, manager)
        assert response.status_code == 201
        body = response.json()
        assert body["kind"] == "percentage" and body["value"] == 30.0
        assert (body["date_from"], body["date_to"], body["brand"], body["note"]) == (
            "2026-10-01",
            "2026-10-31",
            "TP-Link",
            "Q4 co-op",
        )
        [row] = _rows(db)
        assert (row.id, row.advertiser_id, row.campaign_id, row.kind) == (body["id"], ADV, CAMP, "percentage")
        assert (row.date_from, row.date_to, row.value) == (date(2026, 10, 1), date(2026, 10, 31), Decimal("30.00"))
        assert (row.created_by_id, row.updated_by_id) == (admin_user.id, admin_user.id)
        assert body["created_by_id"] == admin_user.id

    def test_a_fixed_amount_keeps_its_two_decimals(self, client, db, manager) -> None:
        response = _create(client, manager, kind="fixed_amount", value="150000.75", brand=None, note=None)
        assert response.status_code == 201
        assert response.json()["value"] == 150000.75
        assert [(r.kind, r.value, r.brand) for r in _rows(db)] == [("fixed_amount", Decimal("150000.75"), None)]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"value": "0"},
            {"value": "100.01"},
            {"value": "-5"},
            {"kind": "fixed_amount", "value": "0"},
            {"kind": "fixed_amount", "value": "10.123"},  # money takes two decimals
            {"kind": "bonus"},
            {"date_from": "2026-11-01", "date_to": "2026-10-31"},
        ],
    )
    def test_out_of_bounds_values_are_422_and_store_nothing(self, client, db, manager, overrides) -> None:
        response = _create(client, manager, **overrides)
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"][0] == "body"  # FastAPI's own body-validation shape
        assert _rows(db) == []

    def test_a_hundred_percent_is_accepted(self, client, manager) -> None:
        assert _create(client, manager, value="100").status_code == 201

    def test_a_campaign_that_is_not_in_the_catalog_is_422(self, client, db, manager) -> None:
        response = _create(client, manager, campaign_id=999)
        assert response.status_code == 422
        assert response.json()["error"]["field"] == "campaign_id"
        assert _create(client, manager, advertiser_id=25713).status_code == 422  # same id, other advertiser
        assert _rows(db) == []


class TestOverlap:
    def test_an_overlapping_range_of_the_same_campaign_is_422(self, client, db, manager) -> None:
        assert _create(client, manager).status_code == 201
        overlapping = _create(client, manager, date_from="2026-10-31", date_to="2026-11-15")  # shares Oct 31
        assert overlapping.status_code == 422
        assert overlapping.json()["error"]["field"] == "date_from"
        assert len(_rows(db)) == 1

    def test_adjacent_ranges_and_other_campaigns_are_fine(self, client, db, manager) -> None:
        assert _create(client, manager).status_code == 201
        assert _create(client, manager, date_from="2026-11-01", date_to="2026-11-30").status_code == 201
        assert _create(client, manager, campaign_id=OTHER).status_code == 201
        assert len(_rows(db)) == 3


class TestUpdate:
    def test_update_replaces_the_fields_and_records_the_editor(self, client, db, manager, viewer, active_user) -> None:
        contribution_id = _create(client, manager).json()["id"]
        grant(db, _role(db, active_user), GESTIONAR)  # the viewer becomes a manager too
        response = client.put(
            f"{BASE}/contributions/{contribution_id}",
            headers=viewer,
            json=_contribution(kind="fixed_amount", value="5000", date_to="2026-10-15", brand="Epson"),
        )
        assert response.status_code == 200
        assert (response.json()["value"], response.json()["date_to"]) == (5000.0, "2026-10-15")
        [row] = _rows(db)
        assert (row.kind, row.value, row.date_to, row.brand) == (
            "fixed_amount",
            Decimal("5000.00"),
            date(2026, 10, 15),
            "Epson",
        )
        assert row.updated_by_id == active_user.id and row.created_by_id != active_user.id

    def test_its_own_range_is_not_an_overlap_but_a_sibling_is(self, client, db, manager) -> None:
        first = _create(client, manager).json()["id"]
        assert _create(client, manager, date_from="2026-11-01", date_to="2026-11-30").status_code == 201
        url = f"{BASE}/contributions/{first}"
        assert client.put(url, headers=manager, json=_contribution(date_to="2026-10-20")).status_code == 200
        clash = client.put(url, headers=manager, json=_contribution(date_to="2026-11-02"))
        assert clash.status_code == 422
        assert _rows(db)[0].date_to == date(2026, 10, 20)

    def test_an_unknown_contribution_is_404(self, client, manager) -> None:
        assert client.put(f"{BASE}/contributions/424242", headers=manager, json=_contribution()).status_code == 404


class TestDelete:
    def test_delete_removes_the_row(self, client, db, manager) -> None:
        contribution_id = _create(client, manager).json()["id"]
        assert client.delete(f"{BASE}/contributions/{contribution_id}", headers=manager).status_code == 204
        assert _rows(db) == []
        assert client.delete(f"{BASE}/contributions/{contribution_id}", headers=manager).status_code == 404

    def test_delete_logs_who_removed_what(self, client, manager, admin_user, caplog) -> None:
        contribution_id = _create(client, manager).json()["id"]
        with caplog.at_level("INFO", logger="app.services.ml_ads.contributions"):
            client.delete(f"{BASE}/contributions/{contribution_id}", headers=manager)
        [record] = [r for r in caplog.records if r.name == "app.services.ml_ads.contributions"]
        message = record.getMessage()
        assert f"contribution {contribution_id} deleted by user {admin_user.id}" in message
        assert f"campaign {CAMP}" in message and "percentage 30.00" in message and "2026-10-01..2026-10-31" in message


def _role(db, user):
    from app.models.rol import Rol

    return db.get(Rol, user.rol_id)

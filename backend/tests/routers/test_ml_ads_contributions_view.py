"""ml-ads-aportes "Por aporte" view (Stitch 55853ac1, owner-approved) -- `GET /api/ml-ads/contributions`.

One row per live aporte of either channel whose range touches the window, with what it covers of the window, and
"Cargado": who loaded it and who last edited it, read from the `auditoria` rows its writes left (owner: "Cargado"
names/dates come from the audit rows). Plus the costs the tiles divide by. DERIVED rows in the SQLite test DB.

Window: October 2026. Product Ads: campaign 351001 spent 300.75 in October (999 in November), campaign 351002 spent
400, and 94.30 has no campaign (NULL and 0). Display (advertiser 25713): campaign 7712 spent 1,000, 7713 spent 200.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.ml_ads import (
    MlAdsCampaign,
    MlAdsCampaignContribution,
    MlAdsDisplayCampaign,
    MlAdsDisplayCampaignDay,
    MlAdsItemDay,
)
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from tests.routers.test_ml_publications_links import grant

BASE = "/api/ml-ads"
GANANCIA = "ml_metricas.ver_ganancia"
ADV, CAMP, OTHER = 714700, 351001, 351002
DISPLAY_ADV = 25713
OCTOBER = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


def _user(db, nombre: str) -> int:
    user = Usuario(
        username=nombre.lower().replace(" ", "."),
        email=f"{nombre.lower().replace(' ', '.')}@example.com",
        nombre=nombre,
        rol=RolUsuario.VENTAS,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user.id


def _item(db, campaign_id, day: date, cost: str, item: str = "MLA1") -> None:
    db.add(
        MlAdsItemDay(
            advertiser_id=ADV, ad_group_id=1, item_id=item, day=day, campaign_id=campaign_id, cost=Decimal(cost), raw={}
        )
    )


def _aporte(db, user_id: int, **fields) -> MlAdsCampaignContribution:
    row = MlAdsCampaignContribution(
        advertiser_id=fields.pop("advertiser_id", ADV),
        created_by_id=user_id,
        updated_by_id=user_id,
        created_at=fields.pop("created_at", datetime(2026, 10, 1, 12, 0)),
        **fields,
    )
    db.add(row)
    db.flush()
    return row


def _audit(db, tipo: TipoAccion, user_id: int, aporte_id: int, when: datetime) -> None:
    after = None if tipo == TipoAccion.ML_ADS_APORTE_BORRADO else {"id": aporte_id}
    before = None if tipo == TipoAccion.ML_ADS_APORTE_CREADO else {"id": aporte_id}
    db.add(Auditoria(usuario_id=user_id, tipo_accion=tipo, valores_anteriores=before, valores_nuevos=after, fecha=when))


@pytest.fixture()
def seeded(db) -> dict:
    lucia, martin = _user(db, "Lucía Fernández"), _user(db, "Martín Gómez")
    db.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=CAMP, name="TP-Link Deco", status="active", raw={}))
    db.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=OTHER, name="Epson EcoTank", status="active", raw={}))
    db.add(MlAdsDisplayCampaign(advertiser_id=DISPLAY_ADV, campaign_id=7712, name="Back to School", raw={}))
    _item(db, CAMP, date(2026, 10, 4), "100.50")
    _item(db, CAMP, date(2026, 10, 5), "200.25")
    _item(db, CAMP, date(2026, 11, 1), "999")
    _item(db, OTHER, date(2026, 10, 10), "400")
    _item(db, None, date(2026, 10, 6), "84.30", item="MLA9")
    _item(db, 0, date(2026, 10, 7), "10", item="MLA8")
    for campaign_id, day, cost in ((7712, date(2026, 10, 3), "1000"), (7713, date(2026, 10, 4), "200")):
        db.add(
            MlAdsDisplayCampaignDay(
                advertiser_id=DISPLAY_ADV, campaign_id=campaign_id, day=day, consumed_budget=Decimal(cost), raw={}
            )
        )
    pct = _aporte(
        db,
        lucia,
        campaign_id=CAMP,
        kind="percentage",
        value=Decimal("20"),
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
        brand="TP-Link",
    )
    fixed = _aporte(
        db,
        martin,
        campaign_id=OTHER,
        kind="fixed_amount",
        value=Decimal("150"),
        settlement="full",
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 31),
        brand="Epson",
        created_at=datetime(2026, 10, 3, 9, 30),
    )
    display = _aporte(
        db,
        lucia,
        advertiser_id=DISPLAY_ADV,
        campaign_id=None,
        channel="display",
        kind="percentage",
        value=Decimal("25"),
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
        brand="Xerox",
    )
    deleted = _aporte(
        db,
        lucia,
        campaign_id=CAMP,
        kind="percentage",
        value=Decimal("5"),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        brand="TP-Link",
        deleted_at=datetime(2026, 10, 20),
        deleted_by_id=martin,
    )
    _aporte(  # November only: outside the window
        db,
        lucia,
        campaign_id=OTHER,
        kind="percentage",
        value=Decimal("10"),
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 30),
        brand="Epson",
    )
    _audit(db, TipoAccion.ML_ADS_APORTE_CREADO, lucia, pct.id, datetime(2026, 10, 2, 10, 0))
    _audit(db, TipoAccion.ML_ADS_APORTE_EDITADO, martin, pct.id, datetime(2026, 10, 18, 16, 0))
    _audit(db, TipoAccion.ML_ADS_APORTE_CREADO, lucia, display.id, datetime(2026, 10, 4, 11, 0))
    _audit(db, TipoAccion.ML_ADS_APORTE_BORRADO, martin, deleted.id, datetime(2026, 10, 20))
    db.flush()
    return {"pct": pct.id, "fixed": fixed.id, "display": display.id}


def _get(client, db, rol_ventas, auth_headers, params=OCTOBER):
    grant(db, rol_ventas, GANANCIA)
    return client.get(f"{BASE}/contributions", headers=auth_headers, params=params)


def test_viewing_needs_ver_ganancia(client, auth_headers, seeded) -> None:
    response = client.get(f"{BASE}/contributions", headers=auth_headers, params=OCTOBER)
    assert response.status_code == 403


def test_the_history_needs_ver_ganancia_too(client, auth_headers, seeded) -> None:
    response = client.get(f"{BASE}/contributions/1/history", headers=auth_headers)
    assert response.status_code == 403


def test_an_inverted_range_is_422(client, db, rol_ventas, auth_headers) -> None:
    response = _get(client, db, rol_ventas, auth_headers, {**OCTOBER, "date_from": "2026-11-01"})
    assert response.status_code == 422


def test_one_row_per_live_aporte_touching_the_window_with_what_it_covers(
    client, db, rol_ventas, auth_headers, seeded
) -> None:
    response = _get(client, db, rol_ventas, auth_headers)
    assert response.status_code == 200
    rows = response.json()["contributions"]
    assert [
        (
            r["id"],
            r["channel"],
            r["brand"],
            r["advertiser_name"],
            r["campaign_id"],
            r["campaign_name"],
            r["kind"],
            r["value"],
            r["settlement"],
            r["covered"],
        )
        for r in rows
    ] == [
        (seeded["pct"], "product_ads", "TP-Link", "TPLINK", CAMP, "TP-Link Deco", "percentage", 20.0, None, 60.15),
        (seeded["display"], "display", "Xerox", "GAUSS", None, None, "percentage", 25.0, None, 300.0),
        (
            seeded["fixed"],
            "product_ads",
            "Epson",
            "TPLINK",
            OTHER,
            "Epson EcoTank",
            "fixed_amount",
            150.0,
            "full",
            150.0,
        ),
    ]


def test_cargado_comes_from_the_audit_rows_and_falls_back_to_the_row_without_them(
    client, db, rol_ventas, auth_headers, seeded
) -> None:
    rows = {r["id"]: r for r in _get(client, db, rol_ventas, auth_headers).json()["contributions"]}
    loaded = {k: (rows[v]["loaded_by"], rows[v]["loaded_at"][:16], rows[v]["edited_by"]) for k, v in seeded.items()}
    assert loaded["pct"] == ("Lucía Fernández", "2026-10-02T10:00", "Martín Gómez")
    assert rows[seeded["pct"]]["edited_at"][:16] == "2026-10-18T16:00"
    assert loaded["display"] == ("Lucía Fernández", "2026-10-04T11:00", None)
    # Loaded before aportes were audited: who and when the row itself recorded.
    assert loaded["fixed"] == ("Martín Gómez", "2026-10-03T09:30", None)
    assert rows[seeded["fixed"]]["edited_at"] is None


def test_the_costs_the_tiles_divide_by(client, db, rol_ventas, auth_headers, seeded) -> None:
    totals = _get(client, db, rol_ventas, auth_headers).json()["totals"]
    assert totals == {"product_ads_cost": 795.05, "display_cost": 1200.0, "no_campaign_cost": 94.3}


def test_the_history_lists_every_audit_row_of_one_aporte_oldest_first(
    client, db, rol_ventas, auth_headers, seeded
) -> None:
    grant(db, rol_ventas, GANANCIA)
    response = client.get(f"{BASE}/contributions/{seeded['pct']}/history", headers=auth_headers)
    assert response.status_code == 200
    events = response.json()["events"]
    assert [(e["action"], e["user"], e["at"][:16]) for e in events] == [
        ("created", "Lucía Fernández", "2026-10-02T10:00"),
        ("edited", "Martín Gómez", "2026-10-18T16:00"),
    ]
    assert (events[0]["before"], events[0]["after"]) == (None, {"id": seeded["pct"]})
    assert events[1]["before"] == {"id": seeded["pct"]}


def test_a_deleted_aporte_keeps_its_history_with_who_deleted_it(client, db, rol_ventas, auth_headers, seeded) -> None:
    grant(db, rol_ventas, GANANCIA)
    deleted_id = (
        db.query(MlAdsCampaignContribution.id).filter(MlAdsCampaignContribution.deleted_at.isnot(None)).scalar()
    )
    events = client.get(f"{BASE}/contributions/{deleted_id}/history", headers=auth_headers).json()["events"]
    assert [(e["action"], e["user"]) for e in events] == [("deleted", "Martín Gómez")]


def test_the_history_of_an_unknown_aporte_is_404(client, db, rol_ventas, auth_headers, seeded) -> None:
    grant(db, rol_ventas, GANANCIA)
    assert client.get(f"{BASE}/contributions/999999/history", headers=auth_headers).status_code == 404

"""Router: the brand-bonus list's filters (`GET /api/sell-in/bonos`), sell-in filters S4.

The Sell in tab's top filters also filter the bonus list: free text over the
bonus's description or brand (`q`), several brands (`marcas`, CSV, exact), the
currency, the state and a date range that keeps the bonuses whose own
`fecha_desde`..`fecha_hasta` range overlaps it. The exact `marca` keeps working.
Non-ASCII case folding is proven on Postgres
(`tests/services/sell_in/test_bonos_filtros_postgres.py`).
"""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP, TipoMoneda

BASE = "/api/sell-in/bonos"


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", costo=10.0),
        ProductoERP(item_id=4513, codigo="SW-16", descripcion="Switch", marca="MERCUSYS", costo=30.0),
        ProductoERP(item_id=4514, codigo="AP-1", descripcion="Access point", marca="UBIQUITI", costo=50.0),
    ]
    for row in rows:
        row.moneda_costo = TipoMoneda.USD
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return admin_auth_headers


def _crear(client, headers, **overrides) -> int:
    body = {
        "marca": "TP-LINK",
        "monto_unit": "2.50",
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-10-31",
        "descripcion": "Acuerdo Q4",
    } | overrides
    resp = client.post(BASE, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _ids(client, headers, **params) -> list[int]:
    resp = client.get(BASE, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == len(data["items"])
    return [b["id"] for b in data["items"]]


def test_q_finds_the_description_or_the_brand_ignoring_case(client, gestor, productos):
    rebate = _crear(client, gestor, descripcion="Rebate switches Q4")
    mercusys = _crear(client, gestor, marca="MERCUSYS", descripcion="Acuerdo anual")
    _crear(client, gestor, marca="UBIQUITI", descripcion=None)

    assert _ids(client, gestor, q="REBATE") == [rebate]
    assert _ids(client, gestor, q="mercu") == [mercusys]
    assert _ids(client, gestor, q="  acuerdo  ") == [mercusys]
    assert _ids(client, gestor, q="100%") == []  # LIKE wildcards stay literal


def test_marcas_takes_several_exact_brands(client, gestor, productos):
    tp = _crear(client, gestor)
    mercusys = _crear(client, gestor, marca="MERCUSYS")
    _crear(client, gestor, marca="UBIQUITI")

    assert _ids(client, gestor, marcas="TP-LINK, MERCUSYS") == [mercusys, tp]
    assert _ids(client, gestor, marcas="TP") == []  # exact, not a substring
    assert len(_ids(client, gestor, marcas=" , ")) == 3  # nothing in the CSV: no filter


def test_the_exact_marca_still_filters_as_before(client, gestor, productos):
    tp = _crear(client, gestor)
    _crear(client, gestor, marca="MERCUSYS")

    assert _ids(client, gestor, marca="TP-LINK") == [tp]
    assert _ids(client, gestor, marca="TP") == []


def test_moneda_filters_by_the_bonus_currency(client, gestor, productos):
    usd = _crear(client, gestor)
    ars = _crear(client, gestor, moneda="ARS")

    assert _ids(client, gestor, moneda="USD") == [usd]
    assert _ids(client, gestor, moneda="ARS") == [ars]
    assert client.get(BASE, params={"moneda": "EUR"}, headers=gestor).status_code == 422


def test_the_period_keeps_the_bonuses_whose_range_overlaps_it_inclusive(client, gestor, productos):
    septiembre = _crear(client, gestor, fecha_desde="2026-09-01", fecha_hasta="2026-09-30")
    octubre = _crear(client, gestor, fecha_desde="2026-10-01", fecha_hasta="2026-10-31")
    q4 = _crear(client, gestor, fecha_desde="2026-10-15", fecha_hasta="2026-12-31")

    assert _ids(client, gestor, fecha_desde="2026-10-01", fecha_hasta="2026-10-31") == [q4, octubre]
    # The bounds touch: the last day of one range is the first day of the period.
    assert _ids(client, gestor, fecha_desde="2026-09-30", fecha_hasta="2026-09-30") == [septiembre]
    # One bound alone: from it on, or up to it.
    assert _ids(client, gestor, fecha_desde="2026-11-01") == [q4]
    assert _ids(client, gestor, fecha_hasta="2026-09-30") == [septiembre]


def test_an_inverted_period_is_a_422(client, gestor, productos):
    resp = client.get(BASE, params={"fecha_desde": "2026-10-31", "fecha_hasta": "2026-10-01"}, headers=gestor)

    assert resp.status_code == 422
    assert resp.json()["error"]["message"] == "La fecha hasta no puede ser anterior a la fecha desde"


def test_the_filters_add_up_with_estado_and_paging(client, gestor, productos):
    viejo = _crear(client, gestor, descripcion="Rebate A")
    _crear(client, gestor, descripcion="Rebate B", moneda="ARS")
    anulado = _crear(client, gestor, descripcion="Rebate C")
    client.post(f"{BASE}/{anulado}/anular", json={}, headers=gestor)
    nuevo = _crear(client, gestor, descripcion="Rebate D")

    page = client.get(
        BASE,
        params={"q": "rebate", "moneda": "USD", "estado": "activa", "marcas": "TP-LINK", "page": 2, "page_size": 1},
        headers=gestor,
    ).json()

    assert page["total"] == 2
    assert [b["id"] for b in page["items"]] == [viejo]
    assert _ids(client, gestor, q="rebate", moneda="USD", estado="activa") == [nuevo, viejo]


def test_marcas_has_a_length_cap_like_q_and_marca(client, gestor, productos):
    assert client.get(BASE, params={"marcas": "X" * 2001}, headers=gestor).status_code == 422
    assert client.get(BASE, params={"marcas": "TP-LINK,EPSON"}, headers=gestor).status_code == 200

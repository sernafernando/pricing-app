"""Sell-out campaigns API (`/api/sell-out/campanas`), feature sell-in-sell-out T6.

Runs on the SQLite test database like the sell-in router tests; the CHECK rules
are proven on Postgres by `tests/models/test_sell_out_schema_postgres.py`.
"""

from __future__ import annotations

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo

BASE = "/api/sell-out/campanas"
VER = "sell_out.ver"
GESTIONAR = "sell_out.gestionar"


def _message(resp) -> str:
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


@pytest.fixture()
def grupos(db):
    rows = [OffsetGrupo(nombre="TP-Link redes"), OffsetGrupo(nombre="Epson tintas")]
    db.add_all(rows)
    db.flush()
    return [row.id for row in rows]


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    grant_permiso(rol_admin, GESTIONAR)
    return admin_auth_headers


@pytest.fixture()
def lector(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    return admin_auth_headers


def _body(grupos: list[int], **overrides) -> dict:
    body = {
        "nombre": "Campaña TP-Link noviembre",
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
        "tipo": "por_unidad",
        "monto_unit": "1500.00",
        "grupo_ids": grupos[:1],
    }
    body.update(overrides)
    return body


def _crear(client, headers, grupos, **overrides) -> dict:
    resp = client.post(BASE, json=_body(grupos, **overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Permissions ─────────────────────────────────────────────────────

ESCRITURAS = [("post", BASE), ("put", f"{BASE}/1"), ("post", f"{BASE}/1/anular")]
LECTURAS = [("get", BASE), ("get", f"{BASE}/1")]


@pytest.mark.parametrize("method,url", ESCRITURAS + LECTURAS)
def test_every_endpoint_requires_a_permission(client, auth_headers, grupos, method, url) -> None:
    kwargs = {"headers": auth_headers}
    if method != "get":
        kwargs["json"] = _body(grupos)
    assert getattr(client, method)(url, **kwargs).status_code == 403


@pytest.mark.parametrize("method,url", ESCRITURAS)
def test_reading_does_not_allow_writing(client, lector, grupos, method, url) -> None:
    resp = getattr(client, method)(url, json=_body(grupos), headers=lector)
    assert resp.status_code == 403
    assert GESTIONAR in _message(resp)


@pytest.mark.parametrize("method,url", ESCRITURAS + LECTURAS)
def test_every_endpoint_requires_authentication(client, grupos, method, url) -> None:
    resp = getattr(client, method)(url, json=_body(grupos)) if method != "get" else client.get(url)
    assert resp.status_code in (401, 403)


# ── Create ──────────────────────────────────────────────────────────


def test_create_per_unit_campaign_with_defaults(client, gestor, grupos, db, admin_user) -> None:
    out = _crear(client, gestor, grupos, moneda="USD", tipo_cambio="1450.5", monto_unit="3", tope_unidades=500)
    assert out["estado"] == "activa"
    assert out["acumulable"] is True
    assert out["base_porcentaje"] == "costo"
    assert (out["moneda"], out["tope_unidades"], out["tope_monto"]) == ("USD", 500, None)
    assert out["usuario_id"] == admin_user.id
    assert out["grupos"] == [{"id": grupos[0], "nombre": "TP-Link redes"}]
    audit = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_CREADA).one()
    assert audit.valores_nuevos["campana_id"] == out["id"]


def test_create_percentage_campaign_on_net_price_not_stackable(client, gestor, grupos) -> None:
    out = _crear(
        client,
        gestor,
        grupos,
        tipo="porcentaje",
        monto_unit=None,
        porcentaje="2.5",
        base_porcentaje="precio_neto",
        acumulable=False,
        tope_monto="200000",
        grupo_ids=grupos,
    )
    assert (out["tipo"], out["base_porcentaje"], out["acumulable"]) == ("porcentaje", "precio_neto", False)
    assert out["monto_unit"] is None
    assert [g["id"] for g in out["grupos"]] == grupos


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"monto_unit": None}, "monto por unidad"),
        ({"monto_unit": "0"}, "monto por unidad"),
        ({"porcentaje": "5"}, "no lleva porcentaje"),
        ({"tipo": "porcentaje", "monto_unit": None}, "porcentaje"),
        ({"tipo": "porcentaje", "monto_unit": None, "porcentaje": "0"}, "porcentaje"),
        ({"tipo": "porcentaje", "monto_unit": None, "porcentaje": "100.5"}, "porcentaje"),
        ({"tipo": "porcentaje", "porcentaje": "5"}, "no lleva monto"),
        ({"fecha_hasta": "2026-10-31"}, "fecha hasta"),
        ({"moneda": "USD"}, "tipo de cambio"),
        ({"tipo_cambio": "0"}, "tipo de cambio"),
        ({"tope_unidades": 0}, "tope"),
        ({"tope_monto": "-1"}, "tope"),
        ({"nombre": "  "}, "nombre"),
        ({"grupo_ids": []}, "grupo"),
        ({"grupo_ids": [999999]}, "999999"),
    ],
)
def test_create_rejects_inconsistent_campaigns(client, gestor, grupos, db, overrides, fragment) -> None:
    resp = client.post(BASE, json=_body(grupos, **overrides), headers=gestor)
    assert resp.status_code == 422, resp.text
    assert fragment in _message(resp)
    assert db.query(SellOutCampana).count() == 0


def test_repeated_groups_link_once(client, gestor, grupos, db) -> None:
    out = _crear(client, gestor, grupos, grupo_ids=[grupos[0], grupos[0]])
    assert db.query(SellOutCampanaGrupo).filter(SellOutCampanaGrupo.campana_id == out["id"]).count() == 1


# ── Read ────────────────────────────────────────────────────────────


def test_list_filters_by_state_validity_text_and_group(client, gestor, grupos) -> None:
    nov = _crear(client, gestor, grupos)
    dic = _crear(
        client,
        gestor,
        grupos,
        nombre="Epson diciembre",
        fecha_desde="2026-12-01",
        fecha_hasta="2026-12-31",
        grupo_ids=grupos[1:],
    )
    anulada = _crear(client, gestor, grupos, nombre="Vieja")
    client.post(f"{BASE}/{anulada['id']}/anular", json={}, headers=gestor)

    def ids(**params) -> list[int]:
        resp = client.get(BASE, params=params, headers=gestor)
        assert resp.status_code == 200, resp.text
        return [c["id"] for c in resp.json()["items"]]

    assert ids() == [dic["id"], anulada["id"], nov["id"]]
    assert ids(estado="activa") == [dic["id"], nov["id"]]
    assert ids(vigente_en="2026-11-30", estado="activa") == [nov["id"]]
    assert ids(vigente_en="2027-01-01") == []
    assert ids(q="epson") == [dic["id"]]
    assert ids(grupo_id=grupos[1]) == [dic["id"]]
    assert client.get(BASE, params={"page_size": 1}, headers=gestor).json()["total"] == 3


def test_get_one_and_unknown_is_404(client, lector, gestor, grupos) -> None:
    out = _crear(client, gestor, grupos)
    assert client.get(f"{BASE}/{out['id']}", headers=lector).json() == out
    assert client.get(f"{BASE}/999999", headers=lector).status_code == 404


# ── Update and void ─────────────────────────────────────────────────


def test_update_replaces_fields_and_groups(client, gestor, grupos, db) -> None:
    out = _crear(client, gestor, grupos)
    body = _body(grupos, nombre="Renombrada", monto_unit="2000", grupo_ids=grupos[1:], acumulable=False)
    resp = client.put(f"{BASE}/{out['id']}", json=body, headers=gestor)
    assert resp.status_code == 200, resp.text
    nueva = resp.json()
    assert (nueva["nombre"], nueva["monto_unit"], nueva["acumulable"]) == ("Renombrada", "2000.00", False)
    assert [g["id"] for g in nueva["grupos"]] == grupos[1:]
    audit = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_EDITADA).one()
    assert audit.valores_anteriores["nombre"] == "Campaña TP-Link noviembre"


def test_update_validates_like_create(client, gestor, grupos) -> None:
    out = _crear(client, gestor, grupos)
    resp = client.put(f"{BASE}/{out['id']}", json=_body(grupos, fecha_hasta="2026-10-01"), headers=gestor)
    assert resp.status_code == 422
    assert client.get(f"{BASE}/{out['id']}", headers=gestor).json()["fecha_hasta"] == "2026-11-30"


def test_void_once_with_reason_then_no_edit(client, gestor, grupos, db) -> None:
    out = _crear(client, gestor, grupos)
    resp = client.post(f"{BASE}/{out['id']}/anular", json={"motivo": "Cargada dos veces"}, headers=gestor)
    assert resp.status_code == 200 and resp.json()["estado"] == "anulada"
    audit = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_ANULADA).one()
    assert audit.comentario == "Cargada dos veces"
    assert client.post(f"{BASE}/{out['id']}/anular", json={}, headers=gestor).status_code == 409
    assert client.put(f"{BASE}/{out['id']}", json=_body(grupos), headers=gestor).status_code == 409


@pytest.mark.parametrize("method,url", [("put", f"{BASE}/999999"), ("post", f"{BASE}/999999/anular")])
def test_unknown_campaign_writes_are_404(client, gestor, grupos, method, url) -> None:
    assert getattr(client, method)(url, json=_body(grupos), headers=gestor).status_code == 404

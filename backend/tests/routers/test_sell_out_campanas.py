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

ESCRITURAS = [("post", BASE), ("put", f"{BASE}/1"), ("post", f"{BASE}/1/anular"), ("post", f"{BASE}/1/tipo-cambio")]
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
    out = _crear(client, gestor, grupos, monto_unit="3", tope_unidades=500)
    assert out["estado"] == "activa"
    assert out["acumulable"] is True
    assert out["base_porcentaje"] == "costo"
    assert (out["moneda"], out["tope_unidades"], out["tope_monto"]) == ("USD", 500, None)
    assert (out["tc_modo"], out["tipo_cambio"], out["tc_definido_en"]) == ("al_cobro", None, None)
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
        ({"tipo": "porcentaje", "monto_unit": None, "porcentaje": "5", "monto_incluye_iva": True}, "IVA"),
        ({"fecha_hasta": "2026-10-31"}, "fecha hasta"),
        ({"tc_modo": "fijo"}, "tipo de cambio fijo"),
        ({"tc_modo": "fijo", "tipo_cambio": "0"}, "mayor a 0"),
        ({"tc_modo": "dia_venta", "tipo_cambio": "1450"}, "día de venta"),
        ({"tipo_cambio": "1450"}, "al cobro"),  # al_cobro (the USD default) never takes a preset rate
        ({"moneda": "ARS", "tc_modo": "fijo", "tipo_cambio": "1450"}, "pesos"),
        ({"moneda": "ARS", "tipo_cambio": "1450"}, "pesos"),
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


@pytest.mark.parametrize(
    "overrides,esperado",
    [
        ({"tc_modo": "fijo", "tipo_cambio": "1450.5"}, ("USD", "fijo", "1450.500000")),
        ({"tc_modo": "dia_venta"}, ("USD", "dia_venta", None)),
        ({"moneda": "ARS"}, ("ARS", None, None)),
    ],
)
def test_create_with_each_fx_mode(client, gestor, grupos, overrides, esperado) -> None:
    out = _crear(client, gestor, grupos, **overrides)
    assert (out["moneda"], out["tc_modo"], out["tipo_cambio"]) == esperado
    assert out["tc_definido_en"] is None


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


def test_vat_flag_defaults_off_and_is_stored_edited_and_audited(client, gestor, grupos, db) -> None:
    assert _crear(client, gestor, grupos)["monto_incluye_iva"] is False
    out = _crear(client, gestor, grupos, monto_incluye_iva=True)
    assert out["monto_incluye_iva"] is True
    creadas = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_CREADA)
    creada = creadas.order_by(Auditoria.id.desc()).first()
    assert creada.valores_nuevos["monto_incluye_iva"] is True
    resp = client.put(f"{BASE}/{out['id']}", json=_body(grupos, monto_incluye_iva=False), headers=gestor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["monto_incluye_iva"] is False
    editada = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_EDITADA).one()
    assert (editada.valores_anteriores["monto_incluye_iva"], editada.valores_nuevos["monto_incluye_iva"]) == (
        True,
        False,
    )
    assert client.get(f"{BASE}/{out['id']}", headers=gestor).json()["monto_incluye_iva"] is False


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


# ── FX rate set at payment (`al_cobro`) ─────────────────────────────


def test_rate_is_set_after_the_campaign_ended_and_can_change(client, gestor, grupos, db) -> None:
    out = _crear(client, gestor, grupos, fecha_desde="2026-01-01", fecha_hasta="2026-01-31")
    url = f"{BASE}/{out['id']}/tipo-cambio"
    resp = client.post(url, json={"tipo_cambio": "1450.5"}, headers=gestor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tipo_cambio"] == "1450.500000"
    assert resp.json()["tc_definido_en"] is not None
    assert client.post(url, json={"tipo_cambio": "1460"}, headers=gestor).json()["tipo_cambio"] == "1460.000000"
    audits = (
        db.query(Auditoria)
        .filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_TC_DEFINIDO)
        .order_by(Auditoria.id)
        .all()
    )
    assert [a.valores_anteriores["tipo_cambio"] for a in audits] == [None, "1450.500000"]
    assert audits[-1].valores_nuevos["tipo_cambio"] == "1460.000000"


def test_editing_keeps_the_rate_set_at_payment(client, gestor, grupos) -> None:
    out = _crear(client, gestor, grupos)
    tc = client.post(f"{BASE}/{out['id']}/tipo-cambio", json={"tipo_cambio": "1450"}, headers=gestor).json()
    for eco in (None, "1450.000000"):
        resp = client.put(f"{BASE}/{out['id']}", json=_body(grupos, nombre="Otra", tipo_cambio=eco), headers=gestor)
        assert resp.status_code == 200, resp.text
        assert (resp.json()["tipo_cambio"], resp.json()["tc_definido_en"]) == ("1450.000000", tc["tc_definido_en"])
    resp = client.put(f"{BASE}/{out['id']}", json=_body(grupos, tipo_cambio="1500"), headers=gestor)
    assert resp.status_code == 422  # the payment rate changes only through its endpoint


@pytest.mark.parametrize(
    "campana,tc,code",
    [
        ({"tc_modo": "fijo", "tipo_cambio": "1450"}, "1500", 422),
        ({"tc_modo": "dia_venta"}, "1500", 422),
        ({"moneda": "ARS"}, "1500", 422),
        ({}, "0", 422),
    ],
)
def test_rate_endpoint_only_for_payment_mode_and_positive(client, gestor, grupos, campana, tc, code) -> None:
    out = _crear(client, gestor, grupos, **campana)
    resp = client.post(f"{BASE}/{out['id']}/tipo-cambio", json={"tipo_cambio": tc}, headers=gestor)
    assert resp.status_code == code, resp.text
    assert client.get(f"{BASE}/{out['id']}", headers=gestor).json()["tipo_cambio"] == out["tipo_cambio"]


def test_rate_endpoint_on_void_or_unknown_campaign(client, gestor, grupos) -> None:
    out = _crear(client, gestor, grupos)
    client.post(f"{BASE}/{out['id']}/anular", json={}, headers=gestor)
    assert client.post(f"{BASE}/{out['id']}/tipo-cambio", json={"tipo_cambio": "1"}, headers=gestor).status_code == 409
    assert client.post(f"{BASE}/999999/tipo-cambio", json={"tipo_cambio": "1"}, headers=gestor).status_code == 404


# ── Numeric bounds (the column types) ───────────────────────────────


def _schema_error_on(resp, campo: str) -> None:
    """A 422 from the request schema (not a business rule) that names `campo`."""
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, list), resp.text
    assert any(error["loc"][-1] == campo for error in detail), resp.text


_TC_FIJO = {"tc_modo": "fijo"}
_PCT = {"tipo": "porcentaje", "monto_unit": None}
LIMITES = {
    "monto_unit": "9999999999999999.99",
    "tope_unidades": 2147483647,
    "tope_monto": "9999999999999999.99",
    "tc_modo": "fijo",
    "tipo_cambio": "999999999999.999999",
}


@pytest.mark.parametrize(
    "campo,valor,extra",
    [
        # NUMERIC(18, 2): 16 whole digits, 2 decimals
        ("monto_unit", "10000000000000000", {}),
        ("monto_unit", "1E+16", {}),
        ("monto_unit", "1.005", {}),
        # NUMERIC(7, 4): 3 whole digits, 4 decimals
        ("porcentaje", "1000", _PCT),
        ("porcentaje", "1E+30", _PCT),
        ("porcentaje", "2.12345", _PCT),
        # NUMERIC(18, 6): 12 whole digits, 6 decimals
        ("tipo_cambio", "1000000000000", _TC_FIJO),
        ("tipo_cambio", "1E+30", _TC_FIJO),
        ("tipo_cambio", "1450.1234567", _TC_FIJO),
        # INTEGER
        ("tope_unidades", 2147483648, {}),
        ("tope_unidades", -2147483649, {}),
        # NUMERIC(18, 2)
        ("tope_monto", "10000000000000000", {}),
        ("tope_monto", "0.001", {}),
    ],
)
def test_create_and_edit_reject_numbers_the_column_cannot_hold(client, gestor, grupos, db, campo, valor, extra) -> None:
    body = _body(grupos, **extra, **{campo: valor})
    _schema_error_on(client.post(BASE, json=body, headers=gestor), campo)
    assert db.query(SellOutCampana).count() == 0
    out = _crear(client, gestor, grupos)
    _schema_error_on(client.put(f"{BASE}/{out['id']}", json=body, headers=gestor), campo)
    assert client.get(f"{BASE}/{out['id']}", headers=gestor).json() == out


def test_the_largest_numbers_the_columns_hold_are_accepted(client, gestor, grupos) -> None:
    """Accepted only; SQLite stores NUMERIC as a float, so the exact values are proven on Postgres
    (`tests/services/sell_out/test_campanas_postgres.py`)."""
    _crear(client, gestor, grupos, **LIMITES)
    _crear(client, gestor, grupos, **_PCT, porcentaje="99.9999")


@pytest.mark.parametrize("valor", ["1000000000000", "1E+30", "1450.1234567"])
def test_rate_endpoint_rejects_rates_the_column_cannot_hold(client, gestor, grupos, valor) -> None:
    out = _crear(client, gestor, grupos)
    resp = client.post(f"{BASE}/{out['id']}/tipo-cambio", json={"tipo_cambio": valor}, headers=gestor)
    _schema_error_on(resp, "tipo_cambio")
    assert client.get(f"{BASE}/{out['id']}", headers=gestor).json() == out


# ── The audit records what the API returns ──────────────────────────

_DECIMALES = ("monto_unit", "porcentaje", "tipo_cambio", "tope_monto")


@pytest.mark.parametrize(
    "overrides",
    [
        {"monto_unit": "3", "tope_monto": "200000", "tc_modo": "fijo", "tipo_cambio": "1450.5"},
        {**_PCT, "porcentaje": "2.5", "tope_monto": "1E+3"},
    ],
)
def test_create_and_edit_audit_the_stored_decimals(client, gestor, grupos, db, overrides) -> None:
    out = _crear(client, gestor, grupos, **overrides)
    creada = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_CREADA).one()
    assert {c: creada.valores_nuevos[c] for c in _DECIMALES} == {c: out[c] for c in _DECIMALES}

    resp = client.put(f"{BASE}/{out['id']}", json=_body(grupos, **overrides, nombre="Otra"), headers=gestor)
    assert resp.status_code == 200, resp.text
    editada = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_EDITADA).one()
    assert {c: editada.valores_nuevos[c] for c in _DECIMALES} == {c: resp.json()[c] for c in _DECIMALES}
    assert {c: editada.valores_anteriores[c] for c in _DECIMALES} == {c: out[c] for c in _DECIMALES}


def test_rate_audit_records_the_set_time_as_the_api_returns_it(client, gestor, grupos, db) -> None:
    out = _crear(client, gestor, grupos)
    resp = client.post(f"{BASE}/{out['id']}/tipo-cambio", json={"tipo_cambio": "1450.5"}, headers=gestor)
    assert resp.status_code == 200, resp.text
    audit = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_TC_DEFINIDO).one()
    assert audit.valores_nuevos["tc_definido_en"] == resp.json()["tc_definido_en"]
    assert audit.valores_nuevos["tipo_cambio"] == resp.json()["tipo_cambio"]
    assert client.get(f"{BASE}/{out['id']}", headers=gestor).json()["tc_definido_en"] == resp.json()["tc_definido_en"]

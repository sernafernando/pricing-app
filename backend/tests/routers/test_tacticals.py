"""Router `/api/tacticals` (tacticals T1): permissions by the tactical's kind, status codes and the contract's shape.
The engines' rules are proven on Postgres (`tests/services/test_tacticals_postgres.py`); SQLite test database."""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP

BASE = "/api/tacticals"


@pytest.fixture()
def productos(db):
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", categoria="Switches"))
    db.flush()


@pytest.fixture()
def sell_out(rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    grant_permiso(rol_admin, "sell_out.gestionar")
    return admin_auth_headers


def _body(**overrides) -> dict:
    body = {
        "tipo": "sell_out",
        "nombre": "Tactical noviembre",
        "marca": "TP-LINK",
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
        "moneda": "ARS",
        "lineas": [{"alcance": "productos", "item_ids": [4512], "modo_monto": "por_unidad", "valor": "10",
                    "tope_unidades": 50}],
    }  # fmt: skip
    body.update(overrides)
    return body


def _message(resp) -> str:
    return resp.json()["error"]["message"]


def test_create_read_and_void(client, productos, sell_out) -> None:
    resp = client.post(BASE, json=_body(), headers=sell_out)
    assert resp.status_code == 201, resp.text
    creado = resp.json()
    [linea] = creado["lineas"]
    assert (linea["linea"], linea["origen"], linea["tope_unidades"], linea["unidades_usadas"]) == (
        1, "sell_out_campana", 50, 0,
    )  # fmt: skip
    assert linea["productos"] == [{"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch"}]

    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json()["lineas"] == creado["lineas"]
    listado = client.get(BASE, params={"q": "noviembre"}, headers=sell_out).json()
    assert (listado["total"], [t["id"] for t in listado["items"]]) == (1, [creado["id"]])
    otra_moneda = "USD" if creado["moneda"] == "ARS" else "ARS"
    assert client.get(BASE, params={"moneda": creado["moneda"]}, headers=sell_out).json()["total"] == 1
    assert client.get(BASE, params={"moneda": otra_moneda}, headers=sell_out).json()["total"] == 0

    anulado = client.post(f"{BASE}/{creado['id']}/anular", json={"motivo": "Sin acuerdo"}, headers=sell_out)
    assert anulado.status_code == 200, anulado.text
    assert (anulado.json()["estado"], anulado.json()["lineas"][0]["estado"]) == ("anulado", "anulada")
    assert client.post(f"{BASE}/{creado['id']}/anular", headers=sell_out).status_code == 409


def test_an_old_client_with_one_brand_and_a_new_one_with_several(client, db, productos, sell_out) -> None:
    """S3: `marca` alone still works and reads back as one brand; `marcas` takes several, `marca` is the first."""
    db.add(ProductoERP(item_id=4513, codigo="SW-5", descripcion="Switch 5", marca="MERCUSYS", categoria="Switches"))
    db.flush()

    viejo = client.post(BASE, json=_body(), headers=sell_out)
    nuevo = client.post(BASE, json=_body(marca=None, marcas=["MERCUSYS", "TP-LINK"]), headers=sell_out)

    assert viejo.status_code == nuevo.status_code == 201, nuevo.text
    assert (viejo.json()["marca"], viejo.json()["marcas"]) == ("TP-LINK", ["TP-LINK"])
    assert (nuevo.json()["marca"], nuevo.json()["marcas"]) == ("MERCUSYS", ["MERCUSYS", "TP-LINK"])
    por_marca = client.get(BASE, params={"marca": "MERCUSYS"}, headers=sell_out).json()
    assert [t["id"] for t in por_marca["items"]] == [nuevo.json()["id"]]


def test_a_broken_rule_is_a_422_naming_its_line(client, productos, sell_out) -> None:
    lineas = [{"alcance": "productos", "item_ids": [999], "modo_monto": "por_unidad", "valor": "10"}]

    resp = client.post(BASE, json=_body(lineas=lineas), headers=sell_out)

    assert resp.status_code == 422
    assert _message(resp) == "Línea 1: no existen los productos 999"


def test_permissions_follow_the_kind(client, productos, sell_out) -> None:
    assert client.post(BASE, json=_body(tipo="sell_in"), headers=sell_out).status_code == 403
    assert client.get(BASE, params={"tipo": "sell_in"}, headers=sell_out).status_code == 403
    assert client.get(BASE, headers=sell_out).status_code == 200  # only the readable kinds


def test_without_permissions_everything_is_403(client, productos, admin_auth_headers) -> None:
    assert client.post(BASE, json=_body(), headers=admin_auth_headers).status_code == 403
    assert client.get(BASE, headers=admin_auth_headers).status_code == 403


def test_unknown_is_404_and_an_inverted_period_is_422(client, sell_out) -> None:
    assert client.get(f"{BASE}/999", headers=sell_out).status_code == 404
    assert client.post(f"{BASE}/999/anular", headers=sell_out).status_code == 404
    resp = client.get(BASE, params={"desde": "2026-11-10", "hasta": "2026-11-01"}, headers=sell_out)
    assert resp.status_code == 422


def test_text_filters_are_bounded(client, sell_out) -> None:
    assert client.get(BASE, params={"q": "x" * 201}, headers=sell_out).status_code == 422
    assert client.get(BASE, params={"marca": "x" * 101}, headers=sell_out).status_code == 422
    assert client.get(BASE, params={"moneda": "EUR"}, headers=sell_out).status_code == 422


def test_the_note_is_bounded(client, productos, sell_out) -> None:
    assert client.post(BASE, json=_body(nota="x" * 2001), headers=sell_out).status_code == 422


def test_create_without_a_scope_keeps_todays_reach(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(), headers=sell_out).json()
    assert (creado["todas_tiendas"], creado["tope_compartido"]) == (True, True)
    assert creado["tiendas"] == [{"tipo": "fuera", "store_id": None}, {"tipo": "tienda_nube", "store_id": None}]


@pytest.fixture()
def sell_in(sell_out, grant_permiso, rol_admin):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return sell_out


def test_a_sell_in_tactical_with_every_store_keeps_todays_reach_and_one_cap(client, productos, sell_in) -> None:
    """S5, owner 2026-11-10: "lo de tiendas no aplica a sell in, es solo para sell out"."""
    resp = client.post(BASE, json=_body(tipo="sell_in", todas_tiendas=True, tope_compartido=False), headers=sell_in)

    assert resp.status_code == 201, resp.text
    creado = resp.json()
    assert (creado["todas_tiendas"], creado["tope_compartido"]) == (True, True)
    assert creado["tiendas"] == [{"tipo": "fuera", "store_id": None}, {"tipo": "tienda_nube", "store_id": None}]


def test_a_sell_in_tactical_narrowed_to_some_stores_or_channels_is_refused(client, productos, sell_in) -> None:
    resp = client.post(
        BASE, json=_body(tipo="sell_in", todas_tiendas=False, tiendas=[{"tipo": "fuera"}]), headers=sell_in
    )

    assert resp.status_code == 422
    assert _message(resp) == (
        "Las tiendas solo se eligen en sell out: un tactical de sell in baja el costo de todas las ventas"
    )
    assert client.get(BASE, params={"tipo": "sell_in"}, headers=sell_in).json()["total"] == 0


def test_a_sell_out_scope_is_accepted_now_its_engine_honours_it(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(todas_tiendas=True), headers=sell_out).json()

    assert (creado["todas_tiendas"], creado["tope_compartido"], creado["tiendas"]) == (True, False, [])


def test_todays_reach_sent_explicitly_is_accepted(client, productos, sell_out) -> None:
    body = _body(todas_tiendas=True, tope_compartido=True, tiendas=[{"tipo": "tienda_nube"}, {"tipo": "fuera"}])

    assert client.post(BASE, json=body, headers=sell_out).status_code == 201


def test_create_with_a_partial_scope_keeps_per_target_caps(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(todas_tiendas=True), headers=sell_out).json()
    assert (creado["todas_tiendas"], creado["tope_compartido"], creado["tiendas"]) == (True, False, [])


def test_create_with_official_stores_and_channels(client, productos, sell_out, db) -> None:
    from app.models.ml_tienda_oficial import MlTiendaOficial

    db.add(MlTiendaOficial(store_id=57997, nombre="GaussOnline", clave="gauss", orden=1, activa=True))
    db.add(MlTiendaOficial(store_id=2645, nombre="TP-Link", clave="tplink", orden=2, activa=True))
    db.flush()

    resp = client.post(
        BASE,
        json=_body(
            todas_tiendas=False,
            tope_compartido=True,
            tiendas=[
                {"tipo": "oficial", "store_id": 57997},
                {"tipo": "oficial", "store_id": 2645},
                {"tipo": "fuera"},
            ],
        ),
        headers=sell_out,
    )
    assert resp.status_code == 201, resp.text
    creado = resp.json()
    assert (creado["todas_tiendas"], creado["tope_compartido"]) == (False, True)
    assert creado["tiendas"] == [
        {"tipo": "oficial", "store_id": 57997},
        {"tipo": "oficial", "store_id": 2645},
        {"tipo": "fuera", "store_id": None},
    ]
    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json()["tiendas"] == creado["tiendas"]


def test_store_scope_rules(client, productos, sell_out, db) -> None:
    from app.models.ml_tienda_oficial import MlTiendaOficial

    db.add(MlTiendaOficial(store_id=57997, nombre="GaussOnline", clave="gauss", orden=1, activa=True))
    db.flush()

    assert client.post(BASE, json=_body(todas_tiendas=False, tiendas=[]), headers=sell_out).status_code == 422
    resp = client.post(
        BASE,
        json=_body(todas_tiendas=True, tiendas=[{"tipo": "oficial", "store_id": 57997}]),
        headers=sell_out,
    )
    assert resp.status_code == 422
    assert "todas las tiendas" in _message(resp)
    resp = client.post(
        BASE,
        json=_body(todas_tiendas=False, tiendas=[{"tipo": "oficial", "store_id": 999}]),
        headers=sell_out,
    )
    assert resp.status_code == 422
    assert "999" in _message(resp)


def test_a_busy_create_is_a_409_and_stores_nothing(client, productos, sell_out, monkeypatch, db) -> None:
    from app.models.tactical import Tactical
    from app.services.sell_out import campanas

    def _recalculando(*_args, **_kwargs):
        raise campanas.SellOutRecalculando("La campaña se está recalculando")

    monkeypatch.setattr(campanas, "crear_campana_sin_commit", _recalculando)

    resp = client.post(BASE, json=_body(), headers=sell_out)

    assert resp.status_code == 409
    assert _message(resp) == "Línea 1: La campaña se está recalculando"
    assert db.query(Tactical).count() == 0


def test_voiding_twice_is_a_409(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(), headers=sell_out).json()
    assert client.post(f"{BASE}/{creado['id']}/anular", headers=sell_out).status_code == 200

    resp = client.post(f"{BASE}/{creado['id']}/anular", headers=sell_out)

    assert resp.status_code == 409
    assert "anulado" in _message(resp)


def test_patch_edits_the_safe_fields_with_the_create_s_permission(
    client, productos, sell_out, admin_auth_headers
) -> None:
    creado = client.post(BASE, json=_body(fecha_hasta="2099-11-30"), headers=sell_out).json()

    resp = client.patch(f"{BASE}/{creado['id']}", json={"nombre": "Tactical extendido", "fecha_hasta": "2099-12-31",
                        "lineas": [{"linea": 1, "tope_unidades": 80}]}, headers=sell_out)  # fmt: skip

    assert resp.status_code == 200, resp.text
    editado = resp.json()
    assert (editado["nombre"], editado["fecha_hasta"], editado["lineas"][0]["tope_unidades"]) == (
        "Tactical extendido", "2099-12-31", 80,
    )  # fmt: skip
    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json() == editado


def test_patch_refuses_what_is_not_editable(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(fecha_hasta="2099-11-30"), headers=sell_out).json()

    for cambio in ({"marca": "OTRA"}, {"lineas": [{"linea": 1, "valor": "20"}]}, {"fecha_desde": "2099-11-02"}):
        assert client.patch(f"{BASE}/{creado['id']}", json=cambio, headers=sell_out).status_code == 422, cambio
    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json()["nombre"] == "Tactical noviembre"


def test_patch_status_codes(client, productos, sell_out, rol_admin, grant_permiso, admin_auth_headers) -> None:
    creado = client.post(BASE, json=_body(fecha_hasta="2099-11-30"), headers=sell_out).json()
    url = f"{BASE}/{creado['id']}"

    resp = client.patch(url, json={"fecha_hasta": "2000-01-01"}, headers=sell_out)
    assert (resp.status_code, _message(resp).startswith("La fecha hasta no puede ser anterior a hoy")) == (422, True)
    assert client.patch(f"{BASE}/999", json={"nombre": "X"}, headers=sell_out).status_code == 404
    client.post(f"{url}/anular", headers=sell_out)
    assert client.patch(url, json={"nombre": "X"}, headers=sell_out).status_code == 409


def test_patch_needs_the_kind_s_gestionar(client, productos, sell_out, admin_auth_headers, db) -> None:
    from app.models.tactical import Tactical

    creado = client.post(BASE, json=_body(fecha_hasta="2099-11-30"), headers=sell_out).json()
    db.query(Tactical).filter(Tactical.id == creado["id"]).update({"tipo": "sell_in"})
    db.flush()

    assert client.patch(f"{BASE}/{creado['id']}", json={"nombre": "X"}, headers=sell_out).status_code == 403


SELL_IN_MARCA = {"alcance": "marca", "marca": "TP-LINK", "modo_monto": "porcentaje", "valor": "3"}


def test_put_replaces_the_whole_definition_under_the_same_id(client, productos, sell_in) -> None:
    creado = client.post(BASE, json=_body(), headers=sell_in).json()

    resp = client.put(f"{BASE}/{creado['id']}", json=_body(tipo="sell_in", lineas=[SELL_IN_MARCA]), headers=sell_in)

    assert resp.status_code == 200, resp.text
    editado = resp.json()
    assert (editado["id"], editado["tipo"], len(editado["lineas"])) == (creado["id"], "sell_in", 1)
    assert (editado["lineas"][0]["origen"], editado["lineas"][0]["modo_monto"]) == ("sell_in_bono", "porcentaje")
    assert client.get(f"{BASE}/{creado['id']}", headers=sell_in).json() == editado


def test_put_needs_the_manage_permission_of_the_new_kind_too(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(), headers=sell_out).json()

    resp = client.put(f"{BASE}/{creado['id']}", json=_body(tipo="sell_in", lineas=[SELL_IN_MARCA]), headers=sell_out)

    assert resp.status_code == 403
    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json()["tipo"] == "sell_out"


def test_put_status_codes(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(), headers=sell_out).json()
    url = f"{BASE}/{creado['id']}"

    assert client.put(f"{BASE}/999", json=_body(), headers=sell_out).status_code == 404
    assert client.put(url, json=_body(nombre=" "), headers=sell_out).status_code == 422
    assert client.put(f"{url}/cobranza", json={"fecha_cobro": "2026-11-10"}, headers=sell_out).status_code == 200
    resp = client.put(url, json=_body(nombre="Otro"), headers=sell_out)
    assert (resp.status_code, "primero deshacé el cobro" in _message(resp)) == (409, True)
    client.delete(f"{url}/cobranza", headers=sell_out)
    client.post(f"{url}/anular", headers=sell_out)
    assert client.put(url, json=_body(nombre="Otro"), headers=sell_out).status_code == 409

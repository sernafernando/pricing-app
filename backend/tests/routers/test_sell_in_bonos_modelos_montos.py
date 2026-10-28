"""Router: a model's own value inside a 'modelos' bonus (`/api/sell-in/bonos`), sell-in-sell-out T23a.

Owner: "sell in y sell out deberían permitir agrupados". `modelos` takes item ids (as before) or objects
`{item_id, monto_unit?, porcentaje?}`; a value of the bonus's kind replaces the bonus's for that model. An item sent
as a bare id keeps the value it had stored; an object's values are what is stored. SQLite test database, like
`test_sell_in_bonos_scopes.py`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInBonoItem

BASE = "/api/sell-in/bonos"


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", categoria="Switches"),
        ProductoERP(item_id=4513, codigo="SW-16", descripcion="Switch", marca="MERCUSYS", categoria="Switches"),
        ProductoERP(item_id=4514, codigo="RT-1", descripcion="Router", marca="TP-LINK", categoria="Routers"),
    ]
    for row in rows:
        row.costo = 10.0
        row.moneda_costo = TipoMoneda.USD
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return admin_auth_headers


def _body(**overrides) -> dict:
    body = {
        "alcance": "modelos",
        "modelos": [{"item_id": 4512, "monto_unit": "3.50"}, {"item_id": 4513}],
        "tipo": "por_unidad",
        "monto_unit": "2.50",
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


def _crear(client, headers, **overrides) -> dict:
    resp = client.post(BASE, json=_body(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _valores(data: dict) -> list:
    return [(m["item_id"], m["monto_unit"], m["porcentaje"]) for m in data["modelos"]]


def _guardados(db, bono_id: int) -> list:
    rows = db.query(SellInBonoItem).filter(SellInBonoItem.bono_id == bono_id).order_by(SellInBonoItem.item_id)
    return [(r.item_id, r.monto_unit, r.porcentaje) for r in rows]


def test_create_stores_and_returns_each_models_own_amount(client, gestor, productos, db):
    data = _crear(client, gestor)

    assert _valores(data) == [(4512, "3.50", None), (4513, None, None)]
    assert data["modelos"][0]["codigo"] == "SW-8"
    assert _guardados(db, data["id"]) == [(4512, Decimal("3.50"), None), (4513, None, None)]
    assert _valores(client.get(f"{BASE}/{data['id']}", headers=gestor).json()) == _valores(data)


def test_a_percentage_bonus_stores_each_models_own_percentage(client, gestor, productos, db):
    data = _crear(
        client,
        gestor,
        tipo="porcentaje",
        monto_unit=None,
        porcentaje="2",
        modelos=[{"item_id": 4512, "porcentaje": "7.5"}, 4513],
    )

    assert _valores(data) == [(4512, None, "7.5000"), (4513, None, None)]


def test_the_old_shape_of_bare_ids_is_still_accepted(client, gestor, productos, db):
    data = _crear(client, gestor, modelos=[4513, 4512, 4513])

    assert _valores(data) == [(4512, None, None), (4513, None, None)]


def test_an_edit_with_objects_replaces_the_values(client, gestor, productos, db):
    data = _crear(client, gestor)

    resp = client.put(
        f"{BASE}/{data['id']}",
        json=_body(modelos=[{"item_id": 4512}, {"item_id": 4514, "monto_unit": "1.25"}]),
        headers=gestor,
    )

    assert resp.status_code == 200, resp.text
    assert _valores(resp.json()) == [(4512, None, None), (4514, "1.25", None)]
    assert _guardados(db, data["id"]) == [(4512, None, None), (4514, Decimal("1.25"), None)]


def test_an_edit_with_bare_ids_keeps_the_stored_values(client, gestor, productos, db):
    data = _crear(client, gestor)

    resp = client.put(f"{BASE}/{data['id']}", json=_body(modelos=[4512, 4514]), headers=gestor)

    assert resp.status_code == 200, resp.text
    assert _guardados(db, data["id"]) == [(4512, Decimal("3.50"), None), (4514, None, None)]


def test_an_edit_to_the_other_kind_drops_kept_values_of_the_old_kind(client, gestor, productos, db):
    data = _crear(client, gestor)

    resp = client.put(
        f"{BASE}/{data['id']}",
        json=_body(tipo="porcentaje", monto_unit=None, porcentaje="2", modelos=[4512, 4513]),
        headers=gestor,
    )

    assert resp.status_code == 200, resp.text
    assert _guardados(db, data["id"]) == [(4512, None, None), (4513, None, None)]


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        (
            {"tipo": "porcentaje", "monto_unit": None, "porcentaje": "2"},
            "Un bono por porcentaje no lleva monto por unidad en el modelo 4512",
        ),
        (
            {"modelos": [{"item_id": 4512, "porcentaje": "2"}]},
            "Un bono por unidad no lleva porcentaje en el modelo 4512",
        ),
        (
            {"modelos": [{"item_id": 4512, "monto_unit": "0"}]},
            "El monto por unidad del modelo 4512 debe ser mayor que cero",
        ),
        (
            {
                "tipo": "porcentaje",
                "monto_unit": None,
                "porcentaje": "2",
                "modelos": [{"item_id": 4512, "porcentaje": "-1"}],
            },
            "El porcentaje del modelo 4512 debe ser mayor que cero",
        ),
        (
            {
                "tipo": "porcentaje",
                "monto_unit": None,
                "porcentaje": "2",
                "modelos": [{"item_id": 4512, "porcentaje": "101"}],
            },
            "El porcentaje del modelo 4512 no puede superar 100",
        ),
        ({"modelos": [{"item_id": 4512, "monto_unit": "1"}, 4512]}, "El modelo 4512 está repetido"),
        (
            {"alcance": "categoria", "categoria": "Switches", "modelos": [{"item_id": 4512, "monto_unit": "1"}]},
            "Un bono por categoría no lleva modelos",
        ),
    ],
)
def test_per_model_value_errors_are_422_with_a_spanish_message(client, gestor, productos, db, overrides, fragment):
    resp = client.post(BASE, json=_body(**overrides), headers=gestor)

    assert resp.status_code == 422, resp.text
    assert fragment in resp.json()["error"]["message"]
    assert db.query(SellInBonoItem).count() == 0


@pytest.mark.parametrize(
    "modelo", [{"item_id": 4512, "monto_unit": "1.234"}, {"item_id": 4512, "porcentaje": "1.23456"}]
)
def test_per_model_values_beyond_the_columns_decimals_are_422(client, gestor, productos, modelo):
    assert client.post(BASE, json=_body(modelos=[modelo]), headers=gestor).status_code == 422


def test_a_model_id_beyond_an_integer_is_refused_by_the_schema(client, gestor, productos):
    # Same bounds as a sell-out campaign's product: rejected before reaching the database.
    resp = client.post(BASE, json=_body(modelos=[{"item_id": 2**31, "monto_unit": "5"}]), headers=gestor)

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"][-1] == "item_id"


def test_the_audit_rows_carry_each_models_own_value(client, gestor, productos, db):
    data = _crear(client, gestor)
    client.put(f"{BASE}/{data['id']}", json=_body(modelos=[{"item_id": 4512, "monto_unit": "4"}]), headers=gestor)

    creado = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_CREADO).one()
    editado = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_EDITADO).one()
    assert creado.valores_nuevos["modelos"] == [4512, 4513]
    assert creado.valores_nuevos["valores_modelos"] == [{"item_id": 4512, "monto_unit": "3.50", "porcentaje": None}]
    assert editado.valores_anteriores["valores_modelos"] == creado.valores_nuevos["valores_modelos"]
    assert editado.valores_nuevos["valores_modelos"] == [{"item_id": 4512, "monto_unit": "4.00", "porcentaje": None}]

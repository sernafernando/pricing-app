"""Router: a sell-in bonus's shared cap (`/api/sell-in/bonos`), sell-in-sell-out T24c.

Owner, 2026-10-28: "muchos rebates aplican a un tope conjunto por ejemplo, tablets y notebooks lenovo que aplica
hasta 3000 USD entre los dos". A bonus takes `tope_unidades` and/or `tope_monto` (in its currency); the response
says what was used of each and what is left. On an edit, a cap field left out keeps what was stored and an explicit
null removes it. SQLite test database, like `test_sell_in_bonos.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem

BASE = "/api/sell-in/bonos"


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(item_id=4512, codigo="TAB-1", descripcion="Tablet", marca="LENOVO", categoria="Tablets"),
        ProductoERP(item_id=4513, codigo="NB-1", descripcion="Notebook", marca="LENOVO", categoria="Notebooks"),
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
        "modelos": [4512, 4513],
        "tipo": "por_unidad",
        "monto_unit": "25.00",
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "tope_monto": "3000.00",
    }
    body.update(overrides)
    return body


def _message(resp) -> str:
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


def _crear(client, headers, **overrides) -> dict:
    resp = client.post(BASE, json=_body(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _tope(data: dict) -> tuple:
    return (data["tope_unidades"], data["tope_monto"], data["tope_unidades_restantes"], data["tope_monto_restante"])


def _generada(db, bono_id: int, usuario_id: int, cantidad: int, monto: str, estado: str = "activa") -> None:
    compra = SellInCompra(
        fecha_compra=date(2026, 10, 10),
        moneda="USD",
        monto_total=Decimal(monto),
        tipo_cambio=Decimal("1450"),
        formula="por_unidad",
        estado=estado,
        usuario_id=usuario_id,
        origen="bono_marca",
        bono_id=bono_id,
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=4512, cantidad=cantidad, costo_base_unit=Decimal("10"), monto_asignado=monto
        )
    )
    db.flush()


def test_create_stores_and_returns_the_cap_with_all_of_it_left(client, gestor, productos, db):
    data = _crear(client, gestor, tope_unidades=120)

    assert _tope(data) == (120, "3000.00", 120, "3000.00")
    bono = db.get(SellInBonoMarca, data["id"])
    assert (bono.tope_unidades, bono.tope_monto) == (120, Decimal("3000.00"))


def test_without_a_cap_nothing_is_left_to_report(client, gestor, productos):
    data = _crear(client, gestor, tope_monto=None)

    assert _tope(data) == (None, None, None, None)


def test_get_reports_what_was_used_and_what_is_left(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor, tope_unidades=100)
    _generada(db, data["id"], admin_user.id, 40, "1000.00")
    _generada(db, data["id"], admin_user.id, 80, "2000.00")
    _generada(db, data["id"], admin_user.id, 500, "9999.00", estado="anulada")  # voided: not used

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert (got["unidades"], got["monto_generado"]) == (120, "3000.00")
    # Used up; more units than the cap only until the worker applies a lowered cap: never below zero.
    assert _tope(got) == (100, "3000.00", 0, "0.00")
    assert _tope(client.get(BASE, headers=gestor).json()["items"][0]) == (100, "3000.00", 0, "0.00")


def test_an_edit_without_the_cap_fields_keeps_them_and_null_removes_them(client, gestor, productos, db):
    data = _crear(client, gestor, tope_unidades=50)
    sin_topes = {k: v for k, v in _body().items() if not k.startswith("tope_")}

    kept = client.put(f"{BASE}/{data['id']}", json=sin_topes, headers=gestor)
    assert kept.status_code == 200, kept.text
    assert _tope(kept.json())[:2] == (50, "3000.00")

    cleared = client.put(f"{BASE}/{data['id']}", json={**sin_topes, "tope_unidades": None}, headers=gestor)
    assert _tope(cleared.json())[:2] == (None, "3000.00")
    changed = client.put(f"{BASE}/{data['id']}", json={**sin_topes, "tope_monto": "1500.50"}, headers=gestor)
    assert _tope(changed.json())[:2] == (None, "1500.50")


def test_the_cap_is_audited(client, gestor, productos, db):
    data = _crear(client, gestor)
    client.put(f"{BASE}/{data['id']}", json=_body(tope_monto="2000.00"), headers=gestor)

    edit = (
        db.query(Auditoria)
        .filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_EDITADO)
        .order_by(Auditoria.id.desc())
        .first()
    )
    assert (edit.valores_anteriores["tope_monto"], edit.valores_nuevos["tope_monto"]) == ("3000.00", "2000.00")


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"tope_unidades": 0}, "El tope de unidades debe ser mayor que cero"),
        ({"tope_unidades": -3}, "El tope de unidades debe ser mayor que cero"),
        ({"tope_monto": "0"}, "El tope de monto debe ser mayor que cero"),
        ({"tope_monto": "-1.00"}, "El tope de monto debe ser mayor que cero"),
    ],
)
def test_a_cap_must_be_positive(client, gestor, productos, overrides, message):
    resp = client.post(BASE, json=_body(**overrides), headers=gestor)

    assert resp.status_code == 422
    assert _message(resp) == message


@pytest.mark.parametrize(
    "overrides",
    [{"tope_monto": "1.005"}, {"tope_unidades": 2**31}, {"tope_unidades": 1.5}, {"tope_unidades": True}],
)
def test_a_cap_out_of_its_column_is_refused_never_rounded(client, gestor, productos, overrides):
    assert client.post(BASE, json=_body(**overrides), headers=gestor).status_code == 422


def test_a_partly_used_cap_reports_the_difference(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor, tope_unidades=100)
    _generada(db, data["id"], admin_user.id, 40, "1000.50")

    assert _tope(client.get(f"{BASE}/{data['id']}", headers=gestor).json()) == (100, "3000.00", 60, "1999.50")


def test_money_used_past_a_lowered_cap_shows_none_left(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor, tope_monto="500.00")
    _generada(db, data["id"], admin_user.id, 40, "1000.00")

    assert _tope(client.get(f"{BASE}/{data['id']}", headers=gestor).json())[3] == "0.00"


def test_changing_the_currency_asks_for_the_money_cap_again(client, gestor, productos):
    data = _crear(client, gestor)
    sin_topes = {k: v for k, v in _body().items() if not k.startswith("tope_")}

    resp = client.put(f"{BASE}/{data['id']}", json={**sin_topes, "moneda": "ARS"}, headers=gestor)
    assert resp.status_code == 422
    assert _message(resp) == "Al cambiar la moneda hay que volver a indicar el tope de monto"

    ok = client.put(
        f"{BASE}/{data['id']}", json={**sin_topes, "moneda": "ARS", "tope_monto": "4500000.00"}, headers=gestor
    )
    assert ok.status_code == 200, ok.text
    assert _tope(ok.json())[:2] == (None, "4500000.00")

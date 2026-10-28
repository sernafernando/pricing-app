"""Independent verifier probes for T24c (#1879): the bonus API with a shared cap. SQLite, like the router tests."""

from __future__ import annotations

import pytest

from app.models.auditoria import Auditoria
from app.models.sell_in import SellInBonoMarca
from tests.routers.test_sell_in_bonos_tope import BASE, _body, _crear, _tope, gestor, productos  # noqa: F401


def _stored(db, bono_id):
    db.expire_all()
    bono = db.get(SellInBonoMarca, bono_id)
    return (
        bono.moneda,
        bono.monto_unit,
        bono.tope_unidades,
        bono.tope_monto,
        bono.fecha_hasta,
        db.query(Auditoria).count(),
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"tope_unidades": 0},
        {"tope_monto": "-1"},
        {"tope_monto": "0"},
        {"tope_monto": "10.005"},
        {"tope_unidades": 2.5},
        {"tope_unidades": True},
        {"moneda": "ARS"},  # currency change while a money cap is stored, cap not resent
    ],
)
def test_rejected_edit_changes_nothing(client, gestor, productos, db, overrides):  # noqa: F811
    data = _crear(client, gestor, tope_unidades=50)
    antes = _stored(db, data["id"])
    body = _body(monto_unit="30.00", fecha_hasta="2026-11-30", **overrides)
    if "tope_monto" not in overrides:
        body.pop("tope_monto", None)  # the cap is not resent: the stored one must stay
    resp = client.put(f"{BASE}/{data['id']}", json=body, headers=gestor)
    assert resp.status_code == 422, resp.text
    assert _stored(db, data["id"]) == antes


def test_rejected_create_writes_nothing(client, gestor, productos, db):  # noqa: F811
    n = db.query(SellInBonoMarca).count()
    a = db.query(Auditoria).count()
    resp = client.post(BASE, json=_body(tope_unidades=0), headers=gestor)
    assert resp.status_code == 422
    assert (db.query(SellInBonoMarca).count(), db.query(Auditoria).count()) == (n, a)


def test_currency_change_with_the_cap_resent_converts_nothing_and_stores_it(client, gestor, productos, db):  # noqa: F811
    data = _crear(client, gestor)
    resp = client.put(f"{BASE}/{data['id']}", json=_body(moneda="ARS", tope_monto="4350000.00"), headers=gestor)
    assert resp.status_code == 200, resp.text
    got = resp.json()
    assert (got["moneda"], got["tope_monto"], got["tope_monto_restante"]) == ("ARS", "4350000.00", "4350000.00")


def test_currency_change_with_explicit_null_clears_the_cap(client, gestor, productos, db):  # noqa: F811
    data = _crear(client, gestor)
    resp = client.put(f"{BASE}/{data['id']}", json=_body(moneda="ARS", tope_monto=None), headers=gestor)
    assert resp.status_code == 200, resp.text
    assert _tope(resp.json()) == (None, None, None, None)


def test_old_client_body_on_edit_keeps_both_caps(client, gestor, productos, db):  # noqa: F811
    data = _crear(client, gestor, tope_unidades=7)
    body = _body(monto_unit="26.00")
    body.pop("tope_monto")
    resp = client.put(f"{BASE}/{data['id']}", json=body, headers=gestor)
    assert resp.status_code == 200, resp.text
    assert _tope(resp.json()) == (7, "3000.00", 7, "3000.00")
    assert resp.json()["monto_unit"] == "26.00"


def test_list_and_detail_carry_the_same_cap_fields(client, gestor, productos):  # noqa: F811
    data = _crear(client, gestor, tope_unidades=9)
    detalle = client.get(f"{BASE}/{data['id']}", headers=gestor).json()
    lista = client.get(BASE, headers=gestor).json()
    assert isinstance(lista, dict) and "items" in lista, lista
    fila = next(f for f in lista["items"] if f["id"] == data["id"])
    for k in ("tope_unidades", "tope_monto", "tope_unidades_restantes", "tope_monto_restante"):
        assert fila[k] == detalle[k]

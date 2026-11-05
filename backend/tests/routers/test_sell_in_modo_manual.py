"""Setting a product's `manual` cost mode through the API (D6, handoffs `sell-in-costos-propuesta.md`): the typed
quantity and unit cost (the approved design's "Cantidad" and "Costo unitario"), the product's cost frozen at save time
and shown in the preview, and the fingerprint covering all three. Owner: "otro permiso aparte para poder setear
cantidad y costo a mano [...] un costo a mano que sea el de reposición por ejemplo". The money is covered on Postgres
(`test_costing_manual_postgres`)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.auditoria import Auditoria
from app.models.producto import ProductoERP, TipoMoneda
from app.models.tipo_cambio import TipoCambio

BASE = "/api/sell-in/productos"
HOY = date.today()


@pytest.fixture()
def manualista(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    for permiso in ("productos.ver", "sell_in.ver", "sell_in.costo_manual"):
        grant_permiso(rol_admin, permiso)
    return admin_auth_headers


def _producto(db, costo, moneda=TipoMoneda.ARS) -> int:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=costo, moneda_costo=moneda))
    db.commit()
    return 4512


def _cuerpo(**extra) -> dict:
    return {"modo": "manual", "desde": HOY.isoformat(), "cantidad": 30, "costo_unit": "52000", **extra}


def test_preview_shows_the_frozen_cost_and_confirm_saves_the_block(client, db, manualista) -> None:
    _producto(db, 50000.0)

    vista = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo(), headers=manualista)
    assert vista.status_code == 200, vista.text
    datos = vista.json()
    # 30 units typed at 52 000 against 50 000 frozen: each raises the cost by 2 000.
    assert (datos["costo_base_unit"], datos["unidades_restantes"], datos["descuento_unit"]) == (
        "50000.000000",
        30,
        "-2000.000000",
    )

    resp = client.post(f"{BASE}/4512/modos", json=_cuerpo(huella=datos["huella"]), headers=manualista)

    assert resp.status_code == 201, resp.text
    fila = resp.json()
    assert (fila["modo"], fila["cantidad"], fila["costo_unit"], fila["costo_base_unit"]) == (
        "manual",
        30,
        "52000.000000",
        "50000.000000",
    )
    auditoria = db.query(Auditoria).one()
    assert {k: auditoria.valores_nuevos[k] for k in ("modo", "cantidad", "costo_unit", "costo_base_unit")} == {
        "modo": "manual",
        "cantidad": 30,
        "costo_unit": "52000.000000",
        "costo_base_unit": "50000.000000",
    }


def test_a_usd_cost_is_frozen_in_pesos_at_todays_rate(client, db, manualista) -> None:
    _producto(db, 100.0, TipoMoneda.USD)
    db.add(TipoCambio(fecha=HOY, moneda="USD", compra=990.0, venta=1000.0))
    db.commit()

    vista = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo(), headers=manualista)

    assert vista.status_code == 200, vista.text
    assert vista.json()["costo_base_unit"] == "100000.000000"


@pytest.mark.parametrize(
    ("costo", "moneda", "mensaje"),
    [
        (None, TipoMoneda.ARS, "The product has no cost to freeze"),
        (100.0, TipoMoneda.USD, "There is no USD rate to freeze the product's cost in pesos"),
    ],
)
def test_without_a_cost_to_freeze_it_is_422(client, db, manualista, costo, moneda, mensaje) -> None:
    _producto(db, costo, moneda)

    resp = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo(), headers=manualista)

    assert resp.status_code == 422
    assert resp.json()["error"]["message"] == mensaje


def test_a_confirm_with_another_quantity_or_cost_than_previewed_is_409(client, db, manualista) -> None:
    _producto(db, 50000.0)
    huella = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo(), headers=manualista).json()["huella"]

    for cambio in ({"cantidad": 31}, {"costo_unit": "51000"}):
        resp = client.post(f"{BASE}/4512/modos", json=_cuerpo(huella=huella, **cambio), headers=manualista)
        assert resp.status_code == 409, resp.text
    assert client.get(f"{BASE}/4512/modos", headers=manualista).json()["historial"] == []


def test_a_confirm_after_the_product_cost_moved_is_409(client, db, manualista) -> None:
    producto = db.get(ProductoERP, _producto(db, 50000.0))
    huella = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo(), headers=manualista).json()["huella"]
    producto.costo = 51000.0
    db.commit()

    resp = client.post(f"{BASE}/4512/modos", json=_cuerpo(huella=huella), headers=manualista)

    assert resp.status_code == 409, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"modo": "manual", "desde": HOY.isoformat()},
        _cuerpo(cantidad=None),
        _cuerpo(costo_unit=None),
        _cuerpo(cantidad=0),
        _cuerpo(cantidad=-3),
        _cuerpo(costo_unit="0"),
        _cuerpo(costo_unit="-1"),
        _cuerpo(cantidad=2.5),
        _cuerpo(costo_unit="1.0000001"),
    ],
)
def test_manual_needs_a_positive_quantity_and_unit_cost(client, db, manualista, cuerpo) -> None:
    _producto(db, 50000.0)

    assert client.post(f"{BASE}/4512/modos/vista-previa", json=cuerpo, headers=manualista).status_code == 422


def test_manual_needs_its_own_permission(client, db, rol_admin, admin_auth_headers, grant_permiso) -> None:
    _producto(db, 50000.0)
    for permiso in ("productos.ver", "sell_in.ver", "sell_in.costo_ponderado", "sell_in.costo_ultimo"):
        grant_permiso(rol_admin, permiso)

    resp = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo(), headers=admin_auth_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "Missing permission: sell_in.costo_manual"

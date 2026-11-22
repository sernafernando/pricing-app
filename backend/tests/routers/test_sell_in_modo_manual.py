"""Setting a product's `manual` cost mode through the API (D6, handoffs `sell-in-costos-propuesta.md`): the typed
quantity and unit cost (the approved design's "Cantidad" and "Costo unitario"), the product's cost frozen at save time
and shown in the preview, and the fingerprint covering all three. Owner: "otro permiso aparte para poder setear
cantidad y costo a mano [...] un costo a mano que sea el de reposición por ejemplo". The money is covered on Postgres
(`test_costing_manual_postgres`)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.producto import ProductoERP, TipoMoneda

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
        _cuerpo(cantidad=2**31),  # past the column's integer
        _cuerpo(costo_unit="1.0000001"),
    ],
)
def test_manual_needs_a_positive_quantity_and_unit_cost(client, db, manualista, cuerpo) -> None:
    _producto(db, 50000.0)

    assert client.post(f"{BASE}/4512/modos/vista-previa", json=cuerpo, headers=manualista).status_code == 422

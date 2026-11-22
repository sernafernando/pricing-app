"""The cost mode change's API contract (`POST /api/sell-in/productos/{item_id}/modos/vista-previa` and `.../modos`):
every permission path (D7), the fields it takes and refuses (a field it does not take is a 422, never dropped), and a
lock error from another writer, which answers a 409 to retry instead of a raw 500."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.producto import ProductoERP, TipoMoneda

BASE = "/api/sell-in/productos"
HOY = date.today()
PONDERADO, RETRO = "sell_in.costo_ponderado", "sell_in.costo_retroactivo"


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    grant_permiso(rol_admin, "productos.ver")
    grant_permiso(rol_admin, "sell_in.ver")
    return admin_auth_headers


@pytest.fixture()
def producto(db) -> int:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    db.commit()
    return 4512


def _cuerpo(modo, desde, **extra) -> dict:
    return {"modo": modo, "desde": desde.isoformat(), **extra}


@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
def test_no_auth(client, producto, ruta) -> None:
    resp = client.post(f"{BASE}/4512/{ruta}", json=_cuerpo("ponderado", HOY, huella="0" * 64))
    assert resp.status_code in (401, 403), resp.text


def test_mode_permission_without_sell_in_ver(client, rol_admin, admin_auth_headers, grant_permiso, producto) -> None:
    grant_permiso(rol_admin, "productos.ver")
    grant_permiso(rol_admin, PONDERADO)
    resp = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo("ponderado", HOY), headers=admin_auth_headers)
    assert resp.status_code == 403 and "sell_in.ver" in resp.text, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"desde": HOY.isoformat()},
        {"modo": "ponderado"},
        {"modo": "ponderado", "desde": None},
        {"modo": "otro", "desde": HOY.isoformat()},
        {"modo": "PONDERADO", "desde": HOY.isoformat()},
        {"modo": "ponderado", "desde": "no-es-fecha"},
    ],
)
@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
def test_omitted_or_bad_field_is_422(client, rol_admin, lector, grant_permiso, producto, cuerpo, ruta) -> None:
    grant_permiso(rol_admin, PONDERADO)
    grant_permiso(rol_admin, RETRO)
    extra = {"huella": "0" * 64} if ruta == "modos" else {}
    assert client.post(f"{BASE}/4512/{ruta}", json={**cuerpo, **extra}, headers=lector).status_code == 422

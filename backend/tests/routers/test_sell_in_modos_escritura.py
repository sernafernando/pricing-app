"""Changing a product's sell-in cost mode through the API (`POST /api/sell-in/productos/{item_id}/modos/vista-previa`
and `POST .../modos`): the mode's own permission, the backdating one, the preview's fingerprint, and the row that
lands in the history. The money itself is covered on Postgres (`test_modos_escritura_postgres`)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.producto import ProductoERP, TipoMoneda

BASE = "/api/sell-in/productos"
HOY = date.today()


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    grant_permiso(rol_admin, "productos.ver")
    grant_permiso(rol_admin, "sell_in.ver")
    return admin_auth_headers


@pytest.fixture()
def ponderador(rol_admin, lector, grant_permiso) -> dict:
    grant_permiso(rol_admin, "sell_in.costo_ponderado")
    return lector


@pytest.fixture()
def producto(db) -> int:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    db.commit()
    return 4512


def _cuerpo(modo: str, desde: date) -> dict:
    return {"modo": modo, "desde": desde.isoformat()}


def test_a_mode_without_its_permission_is_refused_naming_it(client, lector, producto) -> None:
    resp = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo("ponderado", HOY), headers=lector)

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "Missing permission: sell_in.costo_ponderado"


def test_a_past_date_needs_the_backdating_permission(client, ponderador, producto) -> None:
    resp = client.post(
        f"{BASE}/4512/modos/vista-previa", json=_cuerpo("ponderado", HOY - timedelta(days=1)), headers=ponderador
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "Missing permission: sell_in.costo_retroactivo"


def test_an_unknown_product_is_404(client, ponderador) -> None:
    assert (
        client.post(f"{BASE}/9999/modos/vista-previa", json=_cuerpo("ponderado", HOY), headers=ponderador).status_code
        == 404
    )


def test_preview_then_confirm_lands_the_row_in_the_history(client, ponderador, producto) -> None:
    vista = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo("ponderado", HOY), headers=ponderador)
    assert vista.status_code == 200, vista.text
    datos = vista.json()
    assert {k: datos[k] for k in ("ventas_cambian", "unidades_restantes", "descuento_unit")} == {
        "ventas_cambian": 0,
        "unidades_restantes": 0,
        "descuento_unit": None,
    }
    assert client.get(f"{BASE}/4512/modos", headers=ponderador).json()["historial"] == []

    resp = client.post(
        f"{BASE}/4512/modos", json={**_cuerpo("ponderado", HOY), "huella": datos["huella"]}, headers=ponderador
    )

    assert resp.status_code == 201, resp.text
    assert (resp.json()["modo"], resp.json()["desde"], resp.json()["origen"]) == ("ponderado", HOY.isoformat(), "visor")
    assert [f["id"] for f in client.get(f"{BASE}/4512/modos", headers=ponderador).json()["historial"]] == [
        resp.json()["id"]
    ]


def test_a_confirm_that_is_not_what_the_preview_showed_is_409(client, ponderador, producto) -> None:
    datos = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo("ponderado", HOY), headers=ponderador).json()

    # Another date than the one previewed.
    resp = client.post(
        f"{BASE}/4512/modos",
        json={**_cuerpo("ponderado", HOY + timedelta(days=1)), "huella": datos["huella"]},
        headers=ponderador,
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["message"] == "The product changed since the preview: preview again"
    assert client.get(f"{BASE}/4512/modos", headers=ponderador).json()["historial"] == []


def test_any_mode_permission_goes_back_to_fifo(client, rol_admin, lector, grant_permiso, producto) -> None:
    grant_permiso(rol_admin, "sell_in.costo_ultimo")

    assert client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo("fifo", HOY), headers=lector).status_code == 200

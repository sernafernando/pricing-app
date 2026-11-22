"""T5 (sell-in-costo-si) PR A: costo SI replaced the per-product cost modes (S14), so a mode change is refused with
410 and writes no mode row; the history still reads."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInModoProducto

BASE = "/api/sell-in/productos"
HOY = date.today()
MENSAJE = "El modo de costo ya no se puede cambiar: el costo es el costo SI"


@pytest.fixture()
def ponderador(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    for codigo in ("productos.ver", "sell_in.ver", "sell_in.costo_ponderado"):
        grant_permiso(rol_admin, codigo)
    return admin_auth_headers


@pytest.fixture()
def producto(db) -> int:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    db.commit()
    return 4512


@pytest.mark.parametrize(
    "ruta, extra", [("modos/vista-previa", {}), ("modos", {"huella": "0" * 64})], ids=["preview", "confirm"]
)
def test_a_mode_change_is_refused_and_writes_nothing(client, db, ponderador, producto, ruta, extra) -> None:
    cuerpo = {"modo": "ponderado", "desde": HOY.isoformat(), **extra}

    resp = client.post(f"{BASE}/4512/{ruta}", json=cuerpo, headers=ponderador)

    assert resp.status_code == 410
    assert resp.json()["error"]["message"] == MENSAJE
    assert db.query(SellInModoProducto).count() == 0


def test_the_mode_history_still_reads(client, ponderador, producto) -> None:
    resp = client.get(f"{BASE}/4512/modos", headers=ponderador)

    assert resp.status_code == 200
    assert resp.json()["historial"] == []

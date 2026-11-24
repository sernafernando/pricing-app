"""T5 (sell-in-costo-si) PR B: costo SI replaced the FIFO lots and the per-product cost modes, so the lot viewer and
mode API (`/api/sell-in/productos/...`) is gone: every route answers 404, even to an admin holding every permission it
used to need. The product's costo SI history has its own endpoint (`/api/costo-si`)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.producto import ProductoERP, TipoMoneda

BASE = "/api/sell-in/productos"
HOY = date.today().isoformat()


@pytest.fixture()
def admin(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    for codigo in ("productos.ver", "productos.ver_info_compras", "sell_in.ver", "sell_in.costo_ponderado"):
        grant_permiso(rol_admin, codigo)
    return admin_auth_headers


@pytest.fixture()
def producto(db) -> int:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    db.commit()
    return 4512


@pytest.mark.parametrize(
    "metodo, ruta, cuerpo",
    [
        ("get", "/costos", None),
        ("get", "/4512/lotes", None),
        ("get", "/4512/lotes/1/consumos", None),
        ("get", "/4512/modos", None),
        ("post", "/4512/modos/vista-previa", {"modo": "ponderado", "desde": HOY}),
        ("post", "/4512/modos", {"modo": "ponderado", "desde": HOY, "huella": "0" * 64}),
        ("get", "/modo-por-defecto", None),
        ("put", "/modo-por-defecto", {"modo": "ponderado"}),
    ],
    ids=["costos", "lotes", "consumos", "modos", "vista-previa", "confirmar-modo", "modo-por-defecto", "fijar-defecto"],
)
def test_the_lot_and_mode_routes_are_gone(client, admin, producto, metodo, ruta, cuerpo) -> None:
    kwargs = {"headers": admin} if cuerpo is None else {"headers": admin, "json": cuerpo}

    resp = getattr(client, metodo)(f"{BASE}{ruta}", **kwargs)

    assert resp.status_code == 404

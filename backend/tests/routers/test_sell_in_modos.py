"""A product's sell-in cost modes, read only (`GET /api/sell-in/productos/{item_id}/modos`): the dated history and
the mode governing today. No row means FIFO, the default ("Para sell in vamos a mantener el FIFO"). Behind the lot
viewer's permission plus `sell_in.ver`: the rows carry the typed and frozen unit costs."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInModoProducto

BASE = "/api/sell-in/productos"
HOY = date.today()


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


def _modo(db, usuario_id: int, modo: str, desde: date, **manual) -> int:
    fila = SellInModoProducto(item_id=4512, modo=modo, desde=desde, usuario_id=usuario_id, **manual)
    db.add(fila)
    db.commit()
    return fila.id


def test_it_needs_the_permission_that_shows_the_product(client, auth_headers) -> None:
    assert client.get(f"{BASE}/4512/modos", headers=auth_headers).status_code == 403


def test_the_product_permission_alone_does_not_show_the_costs(
    client, rol_admin, admin_auth_headers, grant_permiso, producto
) -> None:
    # `productos.ver` is seeded for GERENTE, PRICING and VENTAS; the unit costs are sell-in information.
    grant_permiso(rol_admin, "productos.ver")

    assert client.get(f"{BASE}/4512/modos", headers=admin_auth_headers).status_code == 403


def test_a_product_without_modes_is_fifo(client, lector, producto) -> None:
    resp = client.get(f"{BASE}/4512/modos", headers=lector)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"item_id": 4512, "vigente": None, "historial": []}


def test_the_history_comes_newest_first_and_today_is_governed_by_the_latest_started(
    client, lector, producto, db, admin_user
) -> None:
    fifo = _modo(db, admin_user.id, "fifo", HOY - timedelta(days=30))
    ponderado = _modo(db, admin_user.id, "ponderado", HOY - timedelta(days=3))
    manual = _modo(
        db,
        admin_user.id,
        "manual",
        HOY + timedelta(days=5),
        cantidad=30,
        costo_unit=Decimal("52000"),
        costo_base_unit=Decimal("50000"),
    )

    data = client.get(f"{BASE}/4512/modos", headers=lector).json()

    assert [x["id"] for x in data["historial"]] == [manual, ponderado, fifo]
    assert data["vigente"]["id"] == ponderado
    programado = data["historial"][0]
    assert (programado["modo"], programado["desde"], programado["cantidad"]) == (
        "manual",
        (HOY + timedelta(days=5)).isoformat(),
        30,
    )
    assert (Decimal(programado["costo_unit"]), Decimal(programado["costo_base_unit"])) == (
        Decimal("52000"),
        Decimal("50000"),
    )
    assert (programado["origen"], programado["compra_id"], programado["usuario_nombre"]) == (
        "visor",
        None,
        admin_user.nombre,
    )
    assert data["historial"][1]["cantidad"] is None


def test_two_changes_on_the_same_day_the_latest_saved_governs(client, lector, producto, db, admin_user) -> None:
    _modo(db, admin_user.id, "ultimo", HOY)
    ultimo_guardado = _modo(db, admin_user.id, "fifo", HOY)

    data = client.get(f"{BASE}/4512/modos", headers=lector).json()

    assert data["vigente"]["id"] == ultimo_guardado
    assert data["historial"][0]["id"] == ultimo_guardado

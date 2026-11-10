"""Sell in "Productos" list (`GET /api/sell-in/productos/costos`): one row per product with units left in its lots,
with its cost mode, units, next sale's sell in per unit and latest purchase, in one request for the whole list. Behind
the lot viewer's permission plus `sell_in.ver` (the cost modes need it). The values are proven on Postgres by
`tests/services/sell_in/test_productos_costo_postgres.py`; this pins the permissions and the response shape."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInModoProducto

URL = "/api/sell-in/productos/costos"
HOY = date.today()


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    grant_permiso(rol_admin, "productos.ver")
    grant_permiso(rol_admin, "sell_in.ver")
    return admin_auth_headers


@pytest.fixture()
def producto(db, admin_user) -> int:
    db.add(
        ProductoERP(
            item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", costo=100.0, moneda_costo=TipoMoneda.ARS
        )
    )
    compra = SellInCompra(
        fecha_compra=HOY - timedelta(days=5),
        moneda="ARS",
        monto_total=Decimal("30.00"),
        usuario_id=admin_user.id,
        estado="activa",
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id,
            item_id=4512,
            cantidad=3,
            costo_base_unit=Decimal("100"),
            monto_asignado=Decimal("30.00"),
        )
    )
    db.add(SellInModoProducto(item_id=4512, modo="ultimo", desde=HOY - timedelta(days=2), usuario_id=admin_user.id))
    db.commit()
    return 4512


def test_it_needs_the_permission_that_shows_the_product(client, auth_headers) -> None:
    assert client.get(URL, headers=auth_headers).status_code == 403
    assert client.get(URL).status_code in (401, 403)


def test_it_needs_sell_in_ver_too(client, rol_admin, admin_auth_headers, grant_permiso) -> None:
    grant_permiso(rol_admin, "productos.ver")

    assert client.get(URL, headers=admin_auth_headers).status_code == 403


def test_each_product_comes_with_its_brand_mode_units_sell_in_and_last_purchase(client, lector, producto) -> None:
    resp = client.get(URL, headers=lector)

    assert resp.status_code == 200, resp.text
    (fila,) = resp.json()["productos"]
    assert {k: v for k, v in fila.items() if k != "sell_in_unit"} == {
        "item_id": 4512,
        "codigo": "SW-8",
        "descripcion": "Switch",
        "marca": "TP-LINK",
        "modo": "ultimo",
        "unidades": 3,
        "ultima_compra": (HOY - timedelta(days=5)).isoformat(),
    }
    assert Decimal(fila["sell_in_unit"]) == Decimal("10")


def test_no_lots_answers_an_empty_list(client, lector) -> None:
    resp = client.get(URL, headers=lector)

    assert resp.status_code == 200
    assert resp.json() == {"productos": []}

"""Sell-in lot viewer API (`/api/sell-in/productos/{item_id}/lotes`): read only, behind the permission that already
shows a product's sell-in figures (the product panel's). The FIFO order and statuses are proven on Postgres by
`tests/services/sell_in/test_visor_lotes_postgres.py`; this pins the permission and the response shape."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.producto import ProductoERP, TipoMoneda
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo
from app.schemas.sell_in_out_producto import SellInProducto
from app.services.sell_in import visor_lotes

BASE = "/api/sell-in/productos"


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    grant_permiso(rol_admin, "productos.ver")
    return admin_auth_headers


@pytest.fixture()
def lineas(db, admin_user) -> dict[str, int]:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    proveedor = Proveedor(nombre="Gauss SA")
    db.add(proveedor)
    db.flush()
    ids: dict[str, int] = {}
    for nombre, fecha, cantidad, monto in (
        ("vieja", date(2026, 10, 1), 2, "20.00"),
        ("nueva", date(2026, 10, 5), 3, "10.00"),
    ):
        compra = SellInCompra(
            fecha_compra=fecha,
            moneda="ARS",
            monto_total=Decimal(monto),
            usuario_id=admin_user.id,
            estado="activa",
            proveedor_id=proveedor.id,
        )
        db.add(compra)
        db.flush()
        linea = SellInCompraItem(
            compra_id=compra.id,
            item_id=4512,
            cantidad=cantidad,
            costo_base_unit=Decimal("100"),
            monto_asignado=Decimal(monto),
        )
        db.add(linea)
        db.flush()
        ids[nombre] = linea.id
    for ref, dia in ((11, 3), (12, 2)):
        db.add(
            SellInConsumo(
                compra_item_id=ids["vieja"],
                canal="ml",
                venta_ref=ref,
                item_id=4512,
                fecha_venta=date(2026, 10, dia),
                unidades=1,
                descuento_ars=Decimal("10.00"),
            )
        )
    db.commit()
    return ids


@pytest.mark.parametrize("url", [f"{BASE}/4512/lotes", f"{BASE}/4512/lotes/1/consumos"])
def test_it_needs_the_permission_that_shows_the_product(client, auth_headers, url) -> None:
    assert client.get(url, headers=auth_headers).status_code == 403
    assert client.get(url).status_code in (401, 403)


def test_the_lots_come_with_their_status_and_the_next_sale(client, lector, lineas) -> None:
    resp = client.get(f"{BASE}/4512/lotes", headers=lector)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [(x["compra_item_id"], x["estado"], x["consumidas"], x["restantes"]) for x in data["lotes"]] == [
        (lineas["vieja"], "agotado", 2, 0),
        (lineas["nueva"], "vigente", 0, 3),
    ]
    assert Decimal(data["lotes"][1]["descuento_unit"]) == Decimal("3.333333")
    assert data["proxima"]["numero"] == 2 and data["proxima"]["restantes"] == 3
    assert data["proxima"]["siguiente"] is None


def test_a_product_without_lots_answers_an_empty_list(client, lector) -> None:
    resp = client.get(f"{BASE}/999/lotes", headers=lector)

    assert resp.status_code == 200
    assert resp.json() == {"item_id": 999, "lotes": [], "proxima": None, "bono_costo": None, "compra_visible": False}


def test_the_consumptions_of_a_lot_are_paginated(client, lector, lineas) -> None:
    url = f"{BASE}/4512/lotes/{lineas['vieja']}/consumos"
    resp = client.get(url, params={"page": 1, "page_size": 1}, headers=lector)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["total"], data["page"], data["page_size"]) == (2, 1, 1)
    assert [(x["canal"], x["venta_ref"], x["fecha_venta"], x["unidades"]) for x in data["items"]] == [
        ("ml", 12, "2026-10-02", 1)
    ]
    assert Decimal(data["items"][0]["descuento_ars"]) == Decimal("10.00")


def test_the_supplier_and_invoices_need_the_purchases_permission(client, lector, lineas) -> None:
    # The same permission that shows Productos' "Últimas compras": without it the lots still come, without who sold.
    lotes = client.get(f"{BASE}/4512/lotes", headers=lector).json()

    assert lotes["compra_visible"] is False
    assert {(x["proveedor"], tuple(x["facturas"])) for x in lotes["lotes"]} == {(None, ())}


def test_with_the_purchases_permission_the_supplier_comes(client, lector, lineas, rol_admin, grant_permiso) -> None:
    grant_permiso(rol_admin, "productos.ver_info_compras")

    lotes = client.get(f"{BASE}/4512/lotes", headers=lector).json()

    assert lotes["compra_visible"] is True
    assert {x["proveedor"] for x in lotes["lotes"]} == {"Gauss SA"}


BONO = SellInProducto(bono_id=7, bono_ids=[7], descuento_unit=1500.0, costo=48500.0)


def _con_bono(monkeypatch) -> list[int]:
    llamadas: list[int] = []

    def bono_costo(_db, item_id, _hoy):
        llamadas.append(item_id)
        return BONO

    monkeypatch.setattr(visor_lotes, "bono_costo", bono_costo)
    return llamadas


def test_the_cost_bonus_comes_when_the_current_lot_is_the_last_one(client, lector, lineas, monkeypatch) -> None:
    _con_bono(monkeypatch)

    data = client.get(f"{BASE}/4512/lotes", headers=lector).json()

    assert data["proxima"]["siguiente"] is None
    assert data["bono_costo"] == {"bono_ids": [7], "descuento_unit": 1500.0}


def test_the_cost_bonus_comes_until_a_future_next_lot(client, lector, lineas, db, admin_user, monkeypatch) -> None:
    _con_bono(monkeypatch)
    compra = SellInCompra(
        fecha_compra=date(2099, 1, 1), moneda="ARS", monto_total=Decimal("5.00"), usuario_id=admin_user.id
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=4512, cantidad=1, costo_base_unit=Decimal("100"), monto_asignado=Decimal("5")
        )
    )
    db.commit()

    data = client.get(f"{BASE}/4512/lotes", headers=lector).json()

    assert data["proxima"]["siguiente"]["estado"] == "desde"
    assert data["bono_costo"] == {"bono_ids": [7], "descuento_unit": 1500.0}


def test_no_cost_bonus_while_a_queued_lot_follows(client, lector, lineas, db, admin_user, monkeypatch) -> None:
    llamadas = _con_bono(monkeypatch)
    compra = SellInCompra(
        fecha_compra=date(2026, 10, 8), moneda="ARS", monto_total=Decimal("5.00"), usuario_id=admin_user.id
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=4512, cantidad=1, costo_base_unit=Decimal("100"), monto_asignado=Decimal("5")
        )
    )
    db.commit()

    data = client.get(f"{BASE}/4512/lotes", headers=lector).json()

    assert data["proxima"]["siguiente"]["estado"] == "en_cola"
    assert (data["bono_costo"], llamadas) == (None, [])


def test_a_page_beyond_any_lot_is_rejected_not_a_server_error(client, lector, lineas) -> None:
    # page x page_size is the SQL OFFSET: a huge page overflowed Postgres' bigint (DataError, 500).
    url = f"{BASE}/4512/lotes/{lineas['vieja']}/consumos"

    assert client.get(url, params={"page": 10**17}, headers=lector).status_code == 422
    assert client.get(url, params={"page": 1_000_000, "page_size": 200}, headers=lector).status_code == 200

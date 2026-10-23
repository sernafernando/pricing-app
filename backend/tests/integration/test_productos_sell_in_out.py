"""`sell_in_out` on the Productos list (`GET /api/productos`) and detail
(`GET /api/productos/{item_id}`) (sell-in-sell-out T9).

Owner rule: "Always show both: cost and cost with sell in; markup and totals
without and with sell out." The new field is additive: null when neither sell in
nor sell out applies (never a fallback value) and every existing field stays as
it was. The money rules themselves are pinned against Postgres in
`tests/services/test_productos_sell_in_out_postgres.py`.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.producto import ProductoERP, ProductoPricing
from app.models.sell_in import SellInCompra, SellInCompraItem
from tests.integration.test_productos_ppp import _guard_incompatible_raw_sql

import app.models.item_cost_list_history  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401
import app.models.precio_gremio_override  # noqa: F401


@pytest.fixture(autouse=True)
def _ventas_ve_productos(grant_permiso, rol_ventas):
    grant_permiso(rol_ventas, "productos.ver")


@pytest.fixture()
def comision(db):
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    db.flush()
    return version


def _producto(db, item_id: int) -> ProductoERP:
    p = ProductoERP(
        item_id=item_id,
        codigo=f"SIO-{item_id}",
        descripcion="Producto",
        costo=1000.0,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=0.0,
    )
    db.add(p)
    db.flush()
    db.add(ProductoPricing(item_id=item_id, precio_lista_ml=1400.0))
    db.flush()
    return p


def _sell_in(db, active_user, item_id: int, cantidad: int = 2, monto: str = "200.00") -> int:
    compra = SellInCompra(
        fecha_compra=date(2020, 1, 1), moneda="ARS", monto_total=monto, estado="activa", usuario_id=active_user.id
    )
    db.add(compra)
    db.flush()
    linea = SellInCompraItem(
        compra_id=compra.id, item_id=item_id, cantidad=cantidad, costo_base_unit=1000, monto_asignado=monto
    )
    db.add(linea)
    db.flush()
    return linea.id


def _listar(client, auth_headers, page_size: int = 10) -> dict:
    response = client.get(f"/api/productos?page=1&page_size={page_size}", headers=auth_headers)
    assert response.status_code == 200, response.text
    return {p["item_id"]: p for p in response.json()["productos"]}


class TestNoData:
    def test_detail_without_sell_in_or_sell_out_is_null_and_keeps_its_fields(self, client, auth_headers, db, comision):
        _producto(db, 9501)
        db.commit()

        data = client.get("/api/productos/9501", headers=auth_headers).json()

        assert data["sell_in_out"] is None
        assert data["costo"] == 1000.0
        assert data["precio_lista_ml"] == 1400.0
        assert data["ppp"] is None

    def test_list_without_sell_in_or_sell_out_is_null(self, client, auth_headers, db, comision):
        _guard_incompatible_raw_sql(db)
        _producto(db, 9502)
        db.commit()

        producto = _listar(client, auth_headers)[9502]

        assert producto["sell_in_out"] is None
        assert producto["costo"] == 1000.0


class TestPayload:
    def test_detail_shows_cost_with_sell_in_and_its_markups(self, client, auth_headers, db, comision, active_user):
        _producto(db, 9511)
        linea = _sell_in(db, active_user, 9511)
        db.commit()

        sio = client.get("/api/productos/9511", headers=auth_headers).json()["sell_in_out"]

        assert sio["sell_in"] == {
            "compra_item_id": linea,
            "descuento_unit": 100.0,
            "costo": 900.0,
            "unidades_restantes": 2,
        }
        assert sio["sell_out"] is None
        assert "clasica" in sio["markups_sell_in"]
        assert sio["markups_sell_in_out"] == {}

    def test_list_shows_the_same_payload_as_the_detail(self, client, auth_headers, db, comision, active_user):
        _guard_incompatible_raw_sql(db)
        _producto(db, 9512)
        _sell_in(db, active_user, 9512)
        db.commit()

        listado = _listar(client, auth_headers)[9512]["sell_in_out"]
        detalle = client.get("/api/productos/9512", headers=auth_headers).json()["sell_in_out"]

        assert listado["sell_in"] == detalle["sell_in"]
        assert listado["markups_sell_in"]["clasica"] == detalle["markups_sell_in"]["clasica"]


class TestQueryCount:
    @pytest.mark.parametrize("page_size", [1, 100])
    def test_list_reads_sell_in_and_sell_out_in_a_bounded_batch(
        self, client, auth_headers, db, comision, active_user, query_counter, page_size
    ):
        _guard_incompatible_raw_sql(db)
        for item_id in (9521, 9522, 9523):
            _producto(db, item_id)
            _sell_in(db, active_user, item_id)
        db.commit()

        with query_counter() as counter:
            response = client.get(f"/api/productos?page=1&page_size={page_size}", headers=auth_headers)

        assert response.status_code == 200, response.text
        sell = [s for s in counter.statements if "sell_in_" in s or "sell_out_" in s]
        assert 1 <= len(sell) <= 5

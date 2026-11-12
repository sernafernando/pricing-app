"""`sell_in_out` on the Tienda listing (`GET /api/productos/tienda`).

Owner (2026-11-12): "en tienda tienen que aplicar los sell in y sell out igual que en el resto de las cosas, tienen
que figurarle los costos más bajos y el plus de ganancia, acordate que tienda no usa las mismas fórmulas porque no
es sobre ml." The field is additive: null when neither applies, and every existing field stays as it was. The scope
and percentage base rules are pinned against Postgres in `tests/services/test_tienda_sell_in_out_postgres.py`.

Hand-computed: cost 1000 ARS, VAT 21%, varios 6.5% and Tienda Nube commission 1% (the defaults); a lot of 2 units
for 200 ARS, so 100 per unit and a cost with sell in of 900.

- gremio, 20% markup: net 1000 x 1.2 = 1200; 1200 / 900 - 1 = 33.33%.
- sugerido, clásica 30% and no extra: net 1300; 1300 / 900 - 1 = 44.44%.
- web_transf, 1500 with VAT: 1500 / 1.21 = 1239.67, less 15 (1%) and 80.58 (6.5% of 1239.67) = 1144.09;
  1144.09 / 900 - 1 = 27.12%.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.markup_tienda import MarkupTiendaProducto
from app.models.producto import ProductoERP, ProductoPricing
from app.models.sell_in import SellInCompra, SellInCompraItem
from tests.integration.test_productos_tienda_orden import _guard_incompatible_raw_sql

import app.models.item_cost_list_history  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401
import app.models.precio_gremio_override  # noqa: F401

CON_SELL_IN, SIN_SELL_IN = 9611, 9612


def _producto(db, item_id: int) -> None:
    db.add(
        ProductoERP(
            item_id=item_id,
            codigo=f"TSIO-{item_id}",
            descripcion="Producto",
            marca="MARCA",
            costo=1000.0,
            moneda_costo="ARS",
            iva=21.0,
            activo=True,
            envio=0.0,
        )
    )
    db.flush()
    db.add(
        ProductoPricing(
            item_id=item_id,
            precio_lista_ml=1400.0,
            markup_calculado=30.0,
            participa_web_transferencia=True,
            precio_web_transferencia=1500.0,
        )
    )
    db.add(MarkupTiendaProducto(item_id=item_id, markup_porcentaje=20.0, activo=True))
    db.flush()


def _sell_in(db, active_user, item_id: int) -> int:
    compra = SellInCompra(
        fecha_compra=date(2020, 1, 1), moneda="ARS", monto_total="200.00", estado="activa", usuario_id=active_user.id
    )
    db.add(compra)
    db.flush()
    linea = SellInCompraItem(
        compra_id=compra.id, item_id=item_id, cantidad=2, costo_base_unit=1000, monto_asignado="200.00"
    )
    db.add(linea)
    db.flush()
    return linea.id


@pytest.fixture()
def catalogo(db, active_user) -> int:
    _guard_incompatible_raw_sql(db)
    _producto(db, CON_SELL_IN)
    _producto(db, SIN_SELL_IN)
    linea = _sell_in(db, active_user, CON_SELL_IN)
    db.commit()
    return linea


def _listar(client, auth_headers) -> dict:
    response = client.get("/api/productos/tienda?page=1&page_size=10", headers=auth_headers)
    assert response.status_code == 200, response.text
    return {p["item_id"]: p for p in response.json()["productos"]}


def test_a_product_without_sell_in_or_sell_out_keeps_its_row(client, auth_headers, catalogo):
    producto = _listar(client, auth_headers)[SIN_SELL_IN]

    assert producto["sell_in_out"] is None
    assert producto["costo"] == 1000.0
    assert producto["markup_gremio"] == pytest.approx(20.0)
    assert producto["markup_sugerido_total"] == pytest.approx(30.0)
    assert producto["precio_web_transferencia"] == 1500.0


def test_a_product_with_sell_in_shows_its_lower_cost_and_the_tienda_extra_profit(client, auth_headers, catalogo):
    producto = _listar(client, auth_headers)[CON_SELL_IN]

    sio = producto["sell_in_out"]
    assert sio["sell_in"] == {
        "compra_item_id": catalogo,
        "bono_id": None,
        "bono_ids": [],
        "descuento_unit": 100.0,
        "costo": 900.0,
        "unidades_restantes": 2,
        "moneda_costo": "ARS",
        "costo_moneda": 900.0,
        "descuento_unit_moneda": 100.0,
    }
    assert sio["sell_out"] == {}
    assert sio["markups_sell_in"] == {"gremio": 33.33, "sugerido": 44.44, "web_transf": 27.12}
    assert sio["markups_sell_in_out"] == {}
    # The plain figures stay as they were.
    assert (producto["costo"], producto["markup_gremio"]) == (1000.0, pytest.approx(20.0))

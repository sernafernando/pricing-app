"""Router: scoped and percentage bonuses (`/api/sell-in/bonos`), sell-in-sell-out T3e-3.

A bonus reaches a brand, a category (`productos_erp.categoria`, exact), some
models (item ids) or one whole invoice (a Compras operation), and pays an
amount per invoiced unit or a percentage of the invoiced net. A body without
`alcance`/`tipo` is a brand, per-unit bonus, as before (`test_sell_in_bonos.py`).
SQLite test database, like `test_sell_in_bonos.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.producto import ProductoERP, TipoMoneda
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInBonoItem, SellInBonoMarca, SellInCompra, SellInCompraItem

BASE = "/api/sell-in/bonos"


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", categoria="Switches"),
        ProductoERP(item_id=4513, codigo="SW-16", descripcion="Switch", marca="MERCUSYS", categoria="Switches"),
        ProductoERP(item_id=4514, codigo="RT-1", descripcion="Router", marca="TP-LINK", categoria="Routers"),
    ]
    for row in rows:
        row.costo = 10.0
        row.moneda_costo = TipoMoneda.USD
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def pedido(db, admin_user) -> PedidoCompra:
    empresa = Empresa(nombre="Gauss", activo=True, orden=0)
    proveedor = Proveedor(nombre="TP-Link Argentina")
    db.add_all([empresa, proveedor])
    db.flush()
    row = PedidoCompra(
        numero="P-00042",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("1000"),
        estado="aprobado",
        tipo="mercaderia",
        creado_por_id=admin_user.id,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return admin_auth_headers


def _message(resp) -> str:
    return resp.json()["error"]["message"]


def _body(**overrides) -> dict:
    body = {
        "alcance": "categoria",
        "categoria": "Switches",
        "tipo": "por_unidad",
        "monto_unit": "2.50",
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


def _crear(client, headers, **overrides) -> dict:
    resp = client.post(BASE, json=_body(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _campos(data: dict) -> dict:
    keys = (
        "alcance",
        "marca",
        "categoria",
        "modelos",
        "pedido_id",
        "pedido_numero",
        "tipo",
        "monto_unit",
        "porcentaje",
    )
    return {k: data[k] for k in keys}


def test_a_category_bonus_is_stored_with_only_its_field(client, gestor, productos, db):
    data = _crear(client, gestor, categoria="  Switches ")

    assert _campos(data) == {
        "alcance": "categoria",
        "marca": None,
        "categoria": "Switches",
        "modelos": [],
        "pedido_id": None,
        "pedido_numero": None,
        "tipo": "por_unidad",
        "monto_unit": "2.50",
        "porcentaje": None,
    }
    bono = db.get(SellInBonoMarca, data["id"])
    assert (bono.alcance, bono.categoria, bono.marca) == ("categoria", "Switches", None)


def test_a_models_bonus_stores_its_items_once_each(client, gestor, productos, db):
    data = _crear(client, gestor, alcance="modelos", categoria=None, modelos=[4513, 4512, 4513])

    assert data["modelos"] == [
        {"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch", "monto_unit": None, "porcentaje": None},
        {"item_id": 4513, "codigo": "SW-16", "descripcion": "Switch", "monto_unit": None, "porcentaje": None},
    ]
    rows = (
        db.query(SellInBonoItem.item_id).filter(SellInBonoItem.bono_id == data["id"]).order_by(SellInBonoItem.item_id)
    )
    assert [r.item_id for r in rows] == [4512, 4513]


def test_an_invoice_bonus_points_at_its_operation(client, gestor, productos, pedido):
    data = _crear(client, gestor, alcance="factura", categoria=None, pedido_id=pedido.id)

    assert (data["pedido_id"], data["pedido_numero"]) == (pedido.id, "P-00042")


def test_a_percentage_bonus_has_no_amount_per_unit(client, gestor, productos, db):
    data = _crear(client, gestor, tipo="porcentaje", monto_unit=None, porcentaje="2.5")

    assert (data["tipo"], data["monto_unit"], data["porcentaje"]) == ("porcentaje", None, "2.5000")
    bono = db.get(SellInBonoMarca, data["id"])
    assert (bono.monto_unit, bono.porcentaje) == (None, Decimal("2.5000"))


def test_a_body_without_scope_and_kind_is_a_brand_bonus_per_unit(client, gestor, productos):
    data = _crear(client, gestor, alcance=None, categoria=None, tipo=None, marca="TP-LINK")

    assert (data["alcance"], data["marca"], data["tipo"], data["monto_unit"]) == (
        "marca",
        "TP-LINK",
        "por_unidad",
        "2.50",
    )


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"categoria": "Heladeras"}, "No hay productos de la categoría Heladeras"),
        ({"categoria": None}, "Falta la categoría del bono"),
        ({"alcance": "modelos", "categoria": None}, "Elegí al menos un modelo"),
        ({"alcance": "modelos", "categoria": None, "modelos": [4512, 999001]}, "No existen los items: 999001"),
        ({"alcance": "factura", "categoria": None}, "Falta el pedido de compra del bono"),
        ({"alcance": "factura", "categoria": None, "pedido_id": 424242}, "No existe el pedido de compra 424242"),
        ({"marca": "TP-LINK"}, "Un bono por categoría no lleva marca"),
        ({"modelos": [4512]}, "Un bono por categoría no lleva modelos"),
        ({"alcance": "marca", "categoria": "Switches", "marca": "TP-LINK"}, "Un bono por marca no lleva categoría"),
        ({"tipo": "porcentaje", "monto_unit": None}, "Falta el porcentaje del bono"),
        ({"tipo": "porcentaje", "porcentaje": "2"}, "Un bono por porcentaje no lleva monto por unidad"),
        ({"tipo": "porcentaje", "monto_unit": None, "porcentaje": "0"}, "El porcentaje debe ser mayor que cero"),
        ({"tipo": "porcentaje", "monto_unit": None, "porcentaje": "100.01"}, "El porcentaje no puede superar 100"),
        ({"porcentaje": "2"}, "Un bono por unidad no lleva porcentaje"),
        ({"monto_unit": None}, "Falta el monto por unidad"),
    ],
)
def test_scope_and_kind_errors_are_422_with_a_spanish_message(client, gestor, productos, db, overrides, fragment):
    resp = client.post(BASE, json=_body(**overrides), headers=gestor)

    assert resp.status_code == 422, resp.text
    assert fragment in _message(resp)
    assert db.query(SellInBonoMarca).count() == 0


@pytest.mark.parametrize("overrides", [{"alcance": "proveedor"}, {"tipo": "fijo"}, {"porcentaje": "2.12345"}])
def test_scope_and_kind_shape_errors_are_422(client, gestor, productos, overrides):
    assert client.post(BASE, json=_body(**overrides), headers=gestor).status_code == 422


def test_edit_replaces_the_models_and_can_change_the_scope(client, gestor, productos, db):
    data = _crear(client, gestor, alcance="modelos", categoria=None, modelos=[4512, 4513])

    menos = client.put(
        f"{BASE}/{data['id']}", json=_body(alcance="modelos", categoria=None, modelos=[4513]), headers=gestor
    )
    marca = client.put(
        f"{BASE}/{data['id']}", json=_body(alcance="marca", categoria=None, marca="TP-LINK"), headers=gestor
    )

    assert menos.status_code == 200, menos.text
    assert [m["item_id"] for m in menos.json()["modelos"]] == [4513]
    assert marca.status_code == 200, marca.text
    assert (marca.json()["alcance"], marca.json()["marca"], marca.json()["modelos"]) == ("marca", "TP-LINK", [])
    assert db.query(SellInBonoItem).filter(SellInBonoItem.bono_id == data["id"]).count() == 0


def test_the_audit_row_carries_scope_kind_and_models(client, gestor, productos, db):
    _crear(
        client,
        gestor,
        alcance="modelos",
        categoria=None,
        modelos=[4513, 4512],
        tipo="porcentaje",
        monto_unit=None,
        porcentaje="3",
    )

    [row] = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_CREADO).all()
    nuevos = row.valores_nuevos
    assert (nuevos["alcance"], nuevos["modelos"], nuevos["tipo"], nuevos["porcentaje"], nuevos["monto_unit"]) == (
        "modelos",
        [4512, 4513],
        "porcentaje",
        "3.0000",
        None,
    )


def test_what_a_bonus_generated_is_reported_per_currency(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor)  # USD
    for moneda, monto in (("USD", "10.00"), ("USD", "5.00"), ("ARS", "1450.00")):
        compra = SellInCompra(
            fecha_compra=date(2026, 10, 10),
            moneda=moneda,
            monto_total=Decimal(monto),
            tipo_cambio=Decimal("1450"),
            formula="por_unidad",
            usuario_id=admin_user.id,
            origen="bono_marca",
            bono_id=data["id"],
        )
        db.add(compra)
        db.flush()
        db.add(
            SellInCompraItem(
                compra_id=compra.id,
                item_id=4512,
                cantidad=1,
                costo_base_unit=Decimal("0"),
                monto_asignado=compra.monto_total,
            )
        )
    db.flush()

    body = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    # A purchase left in another currency (a failed reconcile after a currency edit) is never added to the bonus's.
    assert body["monto_generado"] == "15.00"
    assert body["montos_generados"] == [{"moneda": "ARS", "monto": "1450.00"}, {"moneda": "USD", "monto": "15.00"}]

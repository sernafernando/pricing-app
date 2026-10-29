"""Router: a sell-in bonus over the sale's cost (`base='costo_venta'`), sell-in-sell-out T25d (S30, S33).

Owner, 2026-10-29: "es para operaciones viejas que no tienen la factura cargada". A cost bonus is a % of the cost
recorded on each sale (ARS, brand / category / models, no purchase or invoice); `incluye_iva` (S33) only exists on
it. `base` never changes on an edit: the sales rows a cost bonus generated would count twice. Its generated amount
and cap come from `sell_in_bono_consumos`, not from purchases. SQLite test database, like `test_sell_in_bonos.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInBonoConsumo, SellInBonoMarca, SellInCompra, SellInCompraItem

BASE = "/api/sell-in/bonos"


@pytest.fixture()
def productos(db):
    rows = [ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", costo=10.0)]
    for row in rows:
        row.moneda_costo = TipoMoneda.USD
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return admin_auth_headers


def _costo(**overrides) -> dict:
    body = {
        "base": "costo_venta",
        "alcance": "marca",
        "marca": "TP-LINK",
        "tipo": "porcentaje",
        "porcentaje": "2.71",
        "moneda": "ARS",
        "fecha_desde": "2026-01-01",
        "fecha_hasta": "2026-12-31",
    }
    body.update(overrides)
    return body


def _factura(**overrides) -> dict:
    body = {"marca": "TP-LINK", "monto_unit": "2.50", "moneda": "USD", "fecha_desde": "2026-10-01"}
    body.update({"fecha_hasta": "2026-12-31", "descripcion": "Acuerdo Q4"})
    body.update(overrides)
    return body


def _message(resp) -> str:
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


def _crear(client, headers, body: dict) -> dict:
    resp = client.post(BASE, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _consumo(db, bono_id: int, venta_ref: int, unidades: int, descuento: str) -> None:
    db.add(
        SellInBonoConsumo(
            bono_id=bono_id,
            canal="ml",
            venta_ref=venta_ref,
            item_id=4512,
            fecha_venta=date(2026, 3, 1),
            unidades=unidades,
            descuento_ars=Decimal(descuento),
        )
    )
    db.flush()


def test_create_stores_a_cost_bonus_and_returns_its_fields(client, gestor, productos, db):
    data = _crear(client, gestor, _costo(incluye_iva=True, offset_origen_id=9))

    assert (data["base"], data["incluye_iva"], data["offset_origen_id"]) == ("costo_venta", True, None)
    bono = db.get(SellInBonoMarca, data["id"])
    # `offset_origen_id` is set by the offsets migration script only, never from the API.
    assert (bono.base, bono.incluye_iva, bono.offset_origen_id) == ("costo_venta", True, None)


def test_create_defaults_to_an_invoice_bonus_without_vat(client, gestor, productos):
    data = _crear(client, gestor, _factura())

    assert (data["base"], data["incluye_iva"], data["offset_origen_id"]) == ("factura", False, None)


@pytest.mark.parametrize(
    "body,fragment",
    [
        (_costo(tipo="por_unidad", porcentaje=None, monto_unit="5.00"), "porcentaje"),
        (_costo(moneda="USD"), "ars"),
        (_costo(alcance="factura", marca=None, pedido_id=1), "factura"),
        (_factura(incluye_iva=True), "iva"),
    ],
)
def test_invalid_cost_bonus_combinations_are_422(client, gestor, productos, db, body, fragment):
    resp = client.post(BASE, json=body, headers=gestor)

    assert resp.status_code == 422
    assert fragment in _message(resp).lower()
    assert db.query(SellInBonoMarca).count() == 0


@pytest.mark.parametrize(
    "creado,nueva",
    [(_costo(), "factura"), (_factura(), "costo_venta")],
)
def test_the_base_cannot_change_on_edit(client, gestor, productos, db, creado, nueva):
    data = _crear(client, gestor, creado)
    cuerpo = _costo(base=nueva) if nueva == "costo_venta" else _factura(base=nueva)

    resp = client.put(f"{BASE}/{data['id']}", json=cuerpo, headers=gestor)

    assert resp.status_code == 422
    assert "dos veces" in _message(resp)
    assert db.get(SellInBonoMarca, data["id"]).base == creado.get("base", "factura")


def test_an_edit_without_base_keeps_it_and_validates_against_it(client, gestor, productos, db):
    data = _crear(client, gestor, _costo())
    sin_base = {k: v for k, v in _costo().items() if k != "base"}

    kept = client.put(f"{BASE}/{data['id']}", json={**sin_base, "porcentaje": "3.00"}, headers=gestor)
    assert kept.status_code == 200, kept.text
    assert (kept.json()["base"], kept.json()["porcentaje"]) == ("costo_venta", "3.0000")

    usd = client.put(f"{BASE}/{data['id']}", json={**sin_base, "moneda": "USD"}, headers=gestor)
    assert usd.status_code == 422
    assert "ars" in _message(usd).lower()


def test_incluye_iva_is_editable_on_a_cost_bonus_kept_when_absent_and_audited(client, gestor, productos, db):
    data = _crear(client, gestor, _costo())

    resp = client.put(f"{BASE}/{data['id']}", json=_costo(incluye_iva=True), headers=gestor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["incluye_iva"] is True
    sin_iva = {k: v for k, v in _costo().items() if k != "incluye_iva"}
    assert client.put(f"{BASE}/{data['id']}", json=sin_iva, headers=gestor).json()["incluye_iva"] is True

    assert db.get(SellInBonoMarca, data["id"]).incluye_iva is True
    [creado] = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_CREADO).all()
    assert (creado.valores_nuevos["base"], creado.valores_nuevos["incluye_iva"]) == ("costo_venta", False)
    assert creado.valores_nuevos["offset_origen_id"] is None
    primero = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_EDITADO).first()
    assert (primero.valores_anteriores["incluye_iva"], primero.valores_nuevos["incluye_iva"]) == (False, True)


def test_incluye_iva_on_an_invoice_bonus_edit_is_422(client, gestor, productos):
    data = _crear(client, gestor, _factura())

    resp = client.put(f"{BASE}/{data['id']}", json=_factura(incluye_iva=True), headers=gestor)

    assert resp.status_code == 422
    assert "iva" in _message(resp).lower()


def test_a_cost_bonus_reports_what_its_sales_got_and_its_cap(client, gestor, productos, db):
    data = _crear(client, gestor, _costo(tope_unidades=10, tope_monto="500.00"))
    _consumo(db, data["id"], 1, 3, "120.50")
    _consumo(db, data["id"], 2, 4, "200.25")

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()
    listed = client.get(BASE, headers=gestor).json()["items"][0]

    for fila in (got, listed):
        assert {
            k: fila[k]
            for k in (
                "compras_activas",
                "unidades",
                "monto_generado",
                "montos_generados",
                "tope_unidades_restantes",
                "tope_monto_restante",
            )
        } == {
            "compras_activas": 0,
            "unidades": 7,
            "monto_generado": "320.75",
            "montos_generados": [{"moneda": "ARS", "monto": "320.75"}],
            "tope_unidades_restantes": 3,
            "tope_monto_restante": "179.25",
        }


def test_an_invoice_bonus_response_is_unchanged(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor, _factura(tope_unidades=10))
    compra = SellInCompra(
        fecha_compra=date(2026, 10, 10),
        moneda="USD",
        monto_total=Decimal("10.00"),
        tipo_cambio=Decimal("1450"),
        formula="por_unidad",
        estado="activa",
        usuario_id=admin_user.id,
        origen="bono_marca",
        bono_id=data["id"],
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=4512, cantidad=4, costo_base_unit=Decimal("10"), monto_asignado="10.00"
        )
    )
    db.flush()
    # A stray sales row never counts for an invoice bonus.
    _consumo(db, data["id"], 1, 50, "999.00")

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert {k: v for k, v in got.items() if k not in ("created_at", "updated_at")} == {
        "id": data["id"],
        "alcance": "marca",
        "marca": "TP-LINK",
        "categoria": None,
        "modelos": [],
        "pedido_id": None,
        "pedido_numero": None,
        "tipo": "por_unidad",
        "monto_unit": "2.50",
        "porcentaje": None,
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "descripcion": "Acuerdo Q4",
        "estado": "activa",
        "usuario_id": admin_user.id,
        "compras_activas": 1,
        "unidades": 4,
        "monto_generado": "10.00",
        "montos_generados": [{"moneda": "USD", "monto": "10.00"}],
        "tope_unidades": 10,
        "tope_monto": None,
        "tope_unidades_restantes": 6,
        "tope_monto_restante": None,
        "base": "factura",
        "incluye_iva": False,
        "offset_origen_id": None,
    }

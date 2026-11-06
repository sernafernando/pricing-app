"""API: a sell-in cost bonus over a total split across its products (`POST/PUT /api/sell-in/bonos`, tactical monto
total S4). SQLite test database, like `tests/routers/test_sell_in_bonos_costo.py`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInBonoReparto

BASE = "/api/sell-in/bonos"


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", costo=10.0),
        ProductoERP(item_id=4513, codigo="SW-16", descripcion="Switch 16", marca="TP-LINK", costo=20.0),
    ]
    for row in rows:
        row.moneda_costo = TipoMoneda.ARS
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return admin_auth_headers


def _total(**overrides) -> dict:
    body = {
        "base": "costo_venta",
        "alcance": "marca",
        "marca": "TP-LINK",
        "tipo": "monto_total",
        "monto_total": "1200.00",
        "reparto_criterio": "costo",
        "moneda": "ARS",
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
    }
    body.update(overrides)
    return body


def test_create_returns_the_total_its_criterion_and_its_shares(client, gestor, productos, db):
    resp = client.post(BASE, json=_total(), headers=gestor)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert (data["tipo"], data["monto_total"], data["reparto_criterio"]) == ("monto_total", "1200.00", "costo")
    assert (data["monto_unit"], data["porcentaje"], data["tope_unidades"], data["tope_monto"]) == (
        None,
        None,
        None,
        None,
    )
    # Cost 10 and 20: a third and two thirds.
    assert data["repartos"] == [
        {"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch", "monto": "400.00"},
        {"item_id": 4513, "codigo": "SW-16", "descripcion": "Switch 16", "monto": "800.00"},
    ]
    filas = db.query(SellInBonoReparto.item_id, SellInBonoReparto.monto).order_by(SellInBonoReparto.item_id).all()
    assert filas == [(4512, Decimal("400.00")), (4513, Decimal("800.00"))]


def test_a_negative_total_is_a_422_with_its_message(client, gestor, productos, db):
    resp = client.post(BASE, json=_total(monto_total="-1200.00"), headers=gestor)

    assert resp.status_code == 422
    assert resp.json()["error"]["message"] == (
        "El monto total debe ser mayor que cero: en sell in no se descuenta un monto negativo"
    )
    assert db.query(SellInBonoReparto).count() == 0


def test_a_per_unit_bonus_reads_without_a_total(client, gestor, productos):
    body = _total(tipo="por_unidad", monto_unit="2.50", monto_total=None, reparto_criterio=None)
    resp = client.post(BASE, json=body, headers=gestor)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["monto_unit"] == "2.50"
    assert {"monto_total", "reparto_criterio", "repartos"}.isdisjoint(data)


def test_an_edit_to_equal_parts_resplits(client, gestor, productos):
    bono = client.post(BASE, json=_total(), headers=gestor).json()

    resp = client.put(f"{BASE}/{bono['id']}", json=_total(reparto_criterio="iguales"), headers=gestor)

    assert resp.status_code == 200, resp.text
    assert [(r["item_id"], r["monto"]) for r in resp.json()["repartos"]] == [(4512, "600.00"), (4513, "600.00")]

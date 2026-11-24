"""API: a sell-in cost bonus over a total split across its products (`POST/PUT /api/sell-in/bonos`, tactical monto
total S4). Postgres test database (`tests/routers/_pg_app`), like `tests/routers/test_sell_in_bonos_costo.py`: a cost
bonus reads what costo SI took off its invoices, Postgres-only SQL."""

from __future__ import annotations


import pytest

from app.models.producto import ProductoERP, TipoMoneda
from app.schemas.sell_in_bonos import SellInBonoOut
from tests.routers._pg_app import engine  # noqa: F401 - the fixture, by name

pytestmark = pytest.mark.postgres

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


def test_a_per_unit_bonus_reads_without_a_total(client, gestor, productos):
    body = _total(tipo="por_unidad", monto_unit="2.50", monto_total=None, reparto_criterio=None)
    resp = client.post(BASE, json=body, headers=gestor)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["monto_unit"] == "2.50"
    assert {"monto_total", "reparto_criterio", "repartos"}.isdisjoint(data)


def test_the_published_response_schema_keeps_every_bonus_field():
    # FastAPI publishes a response model with its serialization-mode schema.
    schema = SellInBonoOut.model_json_schema(mode="serialization")
    assert {"id", "tipo", "monto_unit", "porcentaje", "monto_total", "reparto_criterio", "repartos"} <= set(
        schema["properties"]
    )

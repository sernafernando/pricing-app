"""
`GET /api/productos/{item_id}` (`obtener_producto`) returns the markup of each
ML instalment price (3/6/9/12 cuotas) like the listing does.

The detail used to hard-code `markup_3_cuotas`..`markup_12_cuotas` to None,
while it already computed every PVP instalment markup. A screen that edits one
product's prices (Publicaciones ML "Precios" tab) reads this endpoint and must
show the same markups Productos shows for the same product.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.producto import ProductoERP, ProductoPricing

# Force-register ERP stub models (only imported inside endpoint bodies otherwise),
# as test_productos_ppp.py does.
import app.models.item_cost_list_history  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401
import app.models.precio_gremio_override  # noqa: F401

CUOTAS = ("3", "6", "9", "12")


@pytest.fixture()
def producto_con_cuotas(db) -> ProductoERP:
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    p = ProductoERP(
        item_id=9301,
        codigo="TEST-DETAIL-CUOTAS",
        descripcion="Producto con cuotas",
        costo=100.0,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=0.0,
    )
    db.add(p)
    db.flush()
    db.add(
        ProductoPricing(
            item_id=p.item_id,
            precio_lista_ml=1400.0,
            precio_3_cuotas=1500.0,
            precio_6_cuotas=1600.0,
            precio_9_cuotas=1700.0,
            precio_12_cuotas=None,
        )
    )
    db.flush()
    return p


def _guard_incompatible_raw_sql(db):
    """The listing runs two Postgres-only `= ANY(:ids)` lookups unrelated to
    markups (see test_productos_ppp.py); answer them empty on SQLite."""
    original_execute = db.execute

    class _EmptyResult:
        def fetchall(self):
            return []

    def _wrapped(statement, *args, **kwargs):
        sql_text = str(statement)
        if "tienda_nube_productos" in sql_text or "v_ml_catalog_status_latest" in sql_text:
            return _EmptyResult()
        return original_execute(statement, *args, **kwargs)

    db.execute = _wrapped


def test_detail_returns_a_markup_for_each_priced_instalment(client, auth_headers, producto_con_cuotas):
    response = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    for cuota in ("3", "6", "9"):
        assert data[f"markup_{cuota}_cuotas"] is not None, f"markup_{cuota}_cuotas missing: {data}"
    # A higher instalment price over the same cost is a higher markup.
    assert data["markup_3_cuotas"] < data["markup_6_cuotas"] < data["markup_9_cuotas"]
    # No price, no markup.
    assert data["markup_12_cuotas"] is None


def test_detail_instalment_markups_match_the_listing(client, auth_headers, db, producto_con_cuotas):
    _guard_incompatible_raw_sql(db)
    detail = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers).json()
    listing = client.get("/api/productos?page=1&page_size=10", headers=auth_headers).json()["productos"]
    row = next(p for p in listing if p["item_id"] == producto_con_cuotas.item_id)

    for cuota in CUOTAS:
        key = f"markup_{cuota}_cuotas"
        if row[key] is None:
            assert detail[key] is None
        else:
            assert detail[key] == pytest.approx(row[key], abs=0.01), key

"""The offset modal's catalog product search (`GET /api/buscar-productos-catalogo`)
searches `productos_erp` by codigo/descripcion regardless of sales or stock — so a
product with zero sales is findable, unlike the per-channel `buscar-productos`
endpoints which are scoped to sales in the period.

admin_user is full-view, so the PM-scope filter is a no-op here; the PM-scoping
itself is covered as a unit test in tests/services/test_pm_scope.py.
"""

from app.models.producto import ProductoERP


def test_finds_active_product_without_any_sales(client, db, admin_auth_headers):
    db.add(
        ProductoERP(
            item_id=970001,
            codigo="7790000011069",
            descripcion="Notebook sin ventas en el periodo",
            marca="Lenovo",
            categoria="Notebooks",
            activo=True,
        )
    )
    db.commit()

    resp = client.get("/api/buscar-productos-catalogo", params={"q": "1069"}, headers=admin_auth_headers)

    assert resp.status_code == 200, resp.text
    assert 970001 in [p["item_id"] for p in resp.json()]


def test_excludes_inactive_products(client, db, admin_auth_headers):
    db.add(
        ProductoERP(
            item_id=970002,
            codigo="EAN-DISC-1069",
            descripcion="Producto discontinuado",
            marca="Lenovo",
            categoria="Notebooks",
            activo=False,
        )
    )
    db.commit()

    resp = client.get("/api/buscar-productos-catalogo", params={"q": "1069"}, headers=admin_auth_headers)

    assert resp.status_code == 200, resp.text
    assert 970002 not in [p["item_id"] for p in resp.json()]


def test_matches_by_descripcion_too(client, db, admin_auth_headers):
    db.add(
        ProductoERP(
            item_id=970003,
            codigo="SKU-INTERNO-999",
            descripcion="Notebook Gamer ABC",
            marca="Lenovo",
            categoria="Notebooks",
            activo=True,
        )
    )
    db.commit()

    resp = client.get("/api/buscar-productos-catalogo", params={"q": "gamer abc"}, headers=admin_auth_headers)

    assert resp.status_code == 200, resp.text
    assert 970003 in [p["item_id"] for p in resp.json()]

"""`GET /api/categorias`: every category, and with `marca` only the categories that brand has products in (SISO S3:
a tactical brand line picks one of its brand's categories, "los routers solo de tp-link"). SQLite test database."""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP


@pytest.fixture()
def productos(db):
    db.add_all(
        [
            ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", categoria="Switches"),
            ProductoERP(item_id=4513, codigo="NB-1", descripcion="Notebook", marca="LENOVO", categoria="Notebooks"),
            ProductoERP(item_id=4514, codigo="RT-1", descripcion="Router", marca="TP-LINK", categoria="Routers"),
            ProductoERP(item_id=4515, codigo="RT-2", descripcion="Router", marca="TP-LINK", categoria=None),
        ]
    )
    db.flush()


def test_without_a_brand_every_category_comes(client, productos, admin_auth_headers) -> None:
    resp = client.get("/api/categorias", headers=admin_auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"categorias": ["Notebooks", "Routers", "Switches"]}


def test_with_a_brand_only_its_categories_come(client, productos, admin_auth_headers) -> None:
    resp = client.get("/api/categorias", params={"marca": "TP-LINK"}, headers=admin_auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"categorias": ["Routers", "Switches"]}

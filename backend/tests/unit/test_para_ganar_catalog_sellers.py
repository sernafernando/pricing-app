"""Focused tests for PARA GANAR catalog seller roster + dispositions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.para_ganar_catalog_seller import ParaGanarCatalogSeller
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from tests.conftest import make_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def test_sellers_get_requires_auth(client: TestClient) -> None:
    response = client.get("/api/para-ganar/criterios/MLA123/sellers")
    assert response.status_code in (401, 403)


def test_sellers_get_empty_without_catalog(client: TestClient, rma_superadmin_user, db) -> None:
    producto = ProductoERP(item_id=88101, codigo="SKU-PG-SEL", descripcion="Sellers test", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88101", item_id=producto.item_id, codigo="SKU-PG-SEL", activo=True))
    db.commit()

    response = client.get(
        "/api/para-ganar/criterios/MLA88101/sellers",
        headers=_auth(rma_superadmin_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mla"] == "MLA88101"
    assert body["catalog_product_id"] is None
    assert body["sellers"] == []


def test_sellers_put_and_get_disposition(client: TestClient, rma_superadmin_user, db) -> None:
    # Seed roster row directly; competition sync is Postgres-shaped.
    db.add(
        ParaGanarCatalogSeller(
            catalog_product_id="MLA999001",
            seller_id="159206893",
            nickname="MACHOSJUAN",
            disposition="active",
        )
    )
    # Link via competition table if present; otherwise monkey via raw insert into links.
    # Minimal path: insert into ml_publication_links when the model exists.
    from app.models.ml_publication_link import MlPublicationLink

    producto = ProductoERP(item_id=88102, codigo="SKU-PG-SEL2", descripcion="Sellers put", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88102", item_id=producto.item_id, codigo="SKU-PG-SEL2", activo=True))
    db.add(
        MlPublicationLink(
            mla="MLA88102",
            catalog_product_id="MLA999001",
            catalog_listing=True,
        )
    )
    db.commit()

    put = client.put(
        "/api/para-ganar/criterios/MLA88102/sellers",
        headers=_auth(rma_superadmin_user),
        json={
            "sellers": [
                {"seller_id": "159206893", "disposition": "excluded"},
            ]
        },
    )
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["catalog_product_id"] == "MLA999001"
    assert any(s["seller_id"] == "159206893" and s["disposition"] == "excluded" for s in saved["sellers"])
    assert saved["excluded_count"] >= 1

    get = client.get(
        "/api/para-ganar/criterios/MLA88102/sellers",
        headers=_auth(rma_superadmin_user),
    )
    assert get.status_code == 200
    body = get.json()
    assert any(s["seller_id"] == "159206893" and s["disposition"] == "excluded" for s in body["sellers"])
    assert body["excluded_count"] >= 1

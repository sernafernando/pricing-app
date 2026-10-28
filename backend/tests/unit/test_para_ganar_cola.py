"""Focused tests for GET /api/para-ganar/cola and alcance-opciones."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import make_access_token


def test_cola_requires_auth(client: TestClient) -> None:
    response = client.get("/api/para-ganar/cola")
    assert response.status_code in (401, 403)


def test_cola_returns_paginated_items(client: TestClient, rma_superadmin_user) -> None:
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get("/api/para-ganar/cola", headers=headers, params={"page": 1, "page_size": 10})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)
    if body["items"]:
        row = body["items"][0]
        assert "mla" in row
        assert "item_id" in row
        assert row["suggestion_status"] == "none"


def test_alcance_opciones_shape(client: TestClient, rma_superadmin_user) -> None:
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get("/api/para-ganar/alcance-opciones", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["marcas"], list)
    assert isinstance(body["subcategorias"], list)
    assert isinstance(body["pms"], list)
    assert isinstance(body["tipos_publicacion"], list)
    assert isinstance(body["listas_precios"], list)
    known_tipos = {"clasica", "3", "6", "9", "12"}
    tipo_ids = {row["id"] for row in body["tipos_publicacion"]}
    assert tipo_ids <= known_tipos


def test_cola_accepts_scope_filter_params(client: TestClient, rma_superadmin_user) -> None:
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get(
        "/api/para-ganar/cola",
        headers=headers,
        params={
            "page": 1,
            "page_size": 10,
            "q": "MLA",
            "marcas": "NOEXISTE",
            "subcategorias": "999999",
            "pms": "999999",
            "tipos_publicacion": "clasica",
            "pricelists": "4",
            "tiendas": "999999",
            "ean": "NOEXISTE",
            "catalog_product_id": "MLA00000000",
            "costo_usd_min": 999999,
            "costo_usd_max": 999999.5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_cola_rejects_inverted_costo_usd_range(client: TestClient, rma_superadmin_user) -> None:
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get(
        "/api/para-ganar/cola",
        headers=headers,
        params={"costo_usd_min": 100, "costo_usd_max": 10},
    )
    assert response.status_code == 422


def test_cola_rejects_invalid_tienda_token(client: TestClient, rma_superadmin_user) -> None:
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get(
        "/api/para-ganar/cola",
        headers=headers,
        params={"tiendas": "not_a_store"},
    )
    assert response.status_code == 400


def test_cola_tipo_and_pricelist_intersection(client: TestClient, rma_superadmin_user) -> None:
    """Clásica ∩ pricelist 17 (3 cuotas) is empty by definition."""
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get(
        "/api/para-ganar/cola",
        headers=headers,
        params={"tipos_publicacion": "clasica", "pricelists": "17", "page_size": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_alcance_opciones_cascades_on_impossible_ean(client: TestClient, rma_superadmin_user) -> None:
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get(
        "/api/para-ganar/alcance-opciones",
        headers=headers,
        params={"ean": "ZZZ-NO-SUCH-CODIGO-PARA-GANAR"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["marcas"] == []
    assert body["subcategorias"] == []
    assert body["listas_precios"] == []
    assert body["tipos_publicacion"] == []


def test_alcance_listas_cascade_from_tipo(client: TestClient, rma_superadmin_user) -> None:
    """Selected tipo constrains lista options to that cuota bucket (web + PVP)."""
    from app.routers.para_ganar import _pricelists_for_tipos

    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get(
        "/api/para-ganar/alcance-opciones",
        headers=headers,
        params={"tipos_publicacion": "clasica"},
    )
    assert response.status_code == 200, response.text
    allowed = set(_pricelists_for_tipos(["clasica"]))
    for row in response.json()["listas_precios"]:
        assert row["id"] in allowed


def test_alcance_tipos_cascade_from_lista(client: TestClient, rma_superadmin_user) -> None:
    """Selected pricelist 17 (3 cuotas) only offers tipo '3' when present."""
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    response = client.get(
        "/api/para-ganar/alcance-opciones",
        headers=headers,
        params={"pricelists": "17"},
    )
    assert response.status_code == 200, response.text
    tipo_ids = {row["id"] for row in response.json()["tipos_publicacion"]}
    assert tipo_ids <= {"3"}


def test_cola_default_catalog_only_opt_in_traditional(client: TestClient, rma_superadmin_user, db) -> None:
    """Default cola = catalog_listing; checkbox includes traditional sync with catalog id."""
    from app.models.ml_publication_link import MlPublicationLink
    from app.models.producto import ProductoERP
    from app.models.publicacion_ml import PublicacionML

    catalog_id = "MLA-PG-CAT-ONLY-991"
    producto = ProductoERP(item_id=99101, codigo="SKU-PG-CATF", descripcion="catalog filter", costo=10)
    db.add(producto)
    db.flush()
    db.add(
        PublicacionML(
            mla="MLA99101",
            item_id=producto.item_id,
            codigo="SKU-PG-CATF",
            activo=True,
            pricelist_id=4,
        )
    )
    db.add(
        PublicacionML(
            mla="MLA99102",
            item_id=producto.item_id,
            codigo="SKU-PG-CATF",
            activo=True,
            pricelist_id=4,
        )
    )
    db.add(
        MlPublicationLink(
            mla="MLA99101",
            catalog_product_id=catalog_id,
            catalog_listing=True,
        )
    )
    db.add(
        MlPublicationLink(
            mla="MLA99102",
            catalog_product_id=catalog_id,
            catalog_listing=False,
        )
    )
    db.commit()

    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
    catalog_only = client.get(
        "/api/para-ganar/cola",
        headers=headers,
        params={"catalog_product_id": catalog_id, "page_size": 20},
    )
    assert catalog_only.status_code == 200, catalog_only.text
    mlas_default = {row["mla"] for row in catalog_only.json()["items"]}
    assert mlas_default == {"MLA99101"}

    with_trad = client.get(
        "/api/para-ganar/cola",
        headers=headers,
        params={
            "catalog_product_id": catalog_id,
            "incluir_tradicionales_sincronizadas": True,
            "page_size": 20,
        },
    )
    assert with_trad.status_code == 200, with_trad.text
    mlas_trad = {row["mla"] for row in with_trad.json()["items"]}
    assert mlas_trad == {"MLA99101", "MLA99102"}

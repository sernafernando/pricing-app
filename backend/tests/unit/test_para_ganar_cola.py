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
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


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

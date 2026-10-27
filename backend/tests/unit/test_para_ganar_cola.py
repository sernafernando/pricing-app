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
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
